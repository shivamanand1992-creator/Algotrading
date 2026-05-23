"""
Real-time WebSocket market data feed for Angel One SmartAPI.

Provides LiveFeed — a wrapper around SmartWebSocket that:
  - Subscribes to live tick data for a list of instruments.
  - Buffers the last 100 ticks per symbol in a deque.
  - Calls a user-supplied callback on every incoming tick.
  - Auto-reconnects on disconnection with exponential back-off.
  - Exposes start(), stop(), subscribe(), unsubscribe(), get_latest_tick().
"""

import os
import time
import json
import threading
from collections import deque
from datetime import datetime
from typing import Callable, Dict, List, Optional, Any

import pytz
from loguru import logger

from data.angel_client import AngelOneClient

try:
    from SmartApi.SmartWebSocket import SmartWebSocket
except ImportError as _err:
    logger.error(
        f"SmartApi package not found. Install with: pip install smartapi-python  [{_err}]"
    )
    raise

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IST = pytz.timezone("Asia/Kolkata")
_TICK_BUFFER_SIZE = 100       # ticks kept per symbol
_RECONNECT_BASE_DELAY = 2.0   # seconds before first reconnect attempt
_RECONNECT_MAX_DELAY = 120.0  # cap on back-off delay
_RECONNECT_MULTIPLIER = 2.0   # exponential back-off factor
_MAX_RECONNECT_ATTEMPTS = 10  # give up after this many consecutive failures


# ---------------------------------------------------------------------------
# Tick data structure
# ---------------------------------------------------------------------------

def _parse_tick(raw: Any) -> Optional[Dict]:
    """
    Parse the raw WebSocket message into a normalised tick dict.

    Angel One SmartWebSocket delivers ticks as a dict (MODE_LTP, MODE_QUOTE,
    or MODE_SNAP_QUOTE).  We extract what we need and add a local IST
    timestamp.

    Returns None if the message cannot be parsed meaningfully.
    """
    if raw is None:
        return None

    # SmartWebSocket may deliver a list or a dict
    if isinstance(raw, list):
        ticks = []
        for item in raw:
            tick = _parse_tick(item)
            if tick is not None:
                ticks.append(tick)
        return ticks if ticks else None

    if not isinstance(raw, dict):
        return None

    token = str(raw.get("token", raw.get("tk", "")))
    if not token:
        return None

    ltp = float(raw.get("ltp", raw.get("lp", 0.0)) or 0.0)
    volume = int(raw.get("volume", raw.get("v", 0)) or 0)
    oi = int(raw.get("oi", raw.get("oi", 0)) or 0)
    bid = float(raw.get("best_bid_price", raw.get("bp1", 0.0)) or 0.0)
    ask = float(raw.get("best_ask_price", raw.get("sp1", 0.0)) or 0.0)

    # Exchange-provided timestamp (epoch ms) or fall back to local time
    exchange_ts = raw.get("exchange_timestamp", raw.get("ft", None))
    if exchange_ts:
        try:
            ts = datetime.fromtimestamp(int(exchange_ts) / 1000, tz=_IST)
        except (ValueError, TypeError):
            ts = datetime.now(_IST)
    else:
        ts = datetime.now(_IST)

    return {
        "token":     token,
        "ltp":       ltp,
        "volume":    volume,
        "oi":        oi,
        "bid":       bid,
        "ask":       ask,
        "timestamp": ts,
    }


# ---------------------------------------------------------------------------
# LiveFeed class
# ---------------------------------------------------------------------------

class LiveFeed:
    """
    Real-time market data feed over Angel One SmartWebSocket.

    Parameters
    ----------
    client  : AngelOneClient
        An already-connected AngelOneClient instance.  Its feed_token and
        client_code are used to authenticate the WebSocket session.
    symbols : list[dict]
        List of instruments to subscribe to on startup.  Each element must
        contain at least::

            {"exchange_type": int, "token": str}

        ``exchange_type`` follows Angel One's encoding:
            1 = NSE CM, 2 = NSE FO, 3 = BSE CM, 4 = BSE FO

    Usage
    -----
    >>> feed = LiveFeed(client, symbols=[{"exchange_type": 2, "token": "26000"}])
    >>> feed.subscribe(callback=my_handler)
    >>> feed.start()
    >>> # ... trading loop ...
    >>> feed.stop()
    """

    def __init__(self, client: AngelOneClient, symbols: List[Dict]) -> None:
        if not isinstance(client, AngelOneClient):
            raise TypeError("client must be an AngelOneClient instance.")

        self._client: AngelOneClient = client
        self._initial_symbols: List[Dict] = list(symbols)

        # {token_str -> deque of tick dicts}
        self._tick_buffers: Dict[str, deque] = {}
        self._buffer_lock = threading.Lock()

        # User callback — called with each normalised tick dict
        self._callback: Optional[Callable[[Dict], None]] = None
        self._callback_lock = threading.Lock()

        # WebSocket handle
        self._ws: Optional[SmartWebSocket] = None
        self._ws_lock = threading.Lock()

        # Control flags
        self._running = threading.Event()
        self._connected = threading.Event()
        self._stop_event = threading.Event()

        # Reconnection state
        self._reconnect_delay = _RECONNECT_BASE_DELAY
        self._reconnect_attempts = 0

        # Background thread that owns the WS run loop
        self._ws_thread: Optional[threading.Thread] = None

        logger.info(
            f"LiveFeed initialised for {len(self._initial_symbols)} symbol(s)."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[Dict], None]) -> None:
        """
        Register a callback to be invoked on every incoming tick.

        The callback receives a single normalised tick dict::

            {
                "token":     str,
                "ltp":       float,
                "volume":    int,
                "oi":        int,
                "bid":       float,
                "ask":       float,
                "timestamp": datetime (IST-aware),
            }

        Parameters
        ----------
        callback : callable
            Function with signature ``callback(tick: dict) -> None``.
            It is called from the WebSocket receive thread; keep it fast.
        """
        if not callable(callback):
            raise TypeError("callback must be callable.")
        with self._callback_lock:
            self._callback = callback
        logger.info("Tick callback registered.")

    def unsubscribe(self, symbols: List[Dict]) -> None:
        """
        Unsubscribe a list of symbols from the live feed.

        Parameters
        ----------
        symbols : list[dict]
            Same format as constructor: [{"exchange_type": int, "token": str}].
        """
        if not symbols:
            return
        with self._ws_lock:
            if self._ws is None or not self._connected.is_set():
                logger.warning("unsubscribe called but WebSocket is not connected.")
                return
            try:
                self._ws.unsubscribe(symbols)
                tokens = [s.get("token", "?") for s in symbols]
                logger.info(f"Unsubscribed from tokens: {tokens}")
                # Clear buffers for unsubscribed tokens
                with self._buffer_lock:
                    for sym in symbols:
                        token = str(sym.get("token", ""))
                        if token in self._tick_buffers:
                            del self._tick_buffers[token]
            except Exception as exc:
                logger.error(f"Error during unsubscribe: {exc}")

    def start(self) -> None:
        """
        Start the WebSocket connection in a background daemon thread.

        Non-blocking: returns immediately after the thread is launched.
        Call stop() to shut it down.
        """
        if self._running.is_set():
            logger.warning("LiveFeed.start() called but feed is already running.")
            return

        self._stop_event.clear()
        self._running.set()
        self._ws_thread = threading.Thread(
            target=self._run_loop,
            name="LiveFeedWSThread",
            daemon=True,
        )
        self._ws_thread.start()
        logger.info("LiveFeed started — WebSocket thread launched.")

    def stop(self) -> None:
        """
        Gracefully shut down the WebSocket feed.

        Blocks until the background thread exits (up to 10 seconds).
        """
        logger.info("LiveFeed stop requested.")
        self._stop_event.set()
        self._running.clear()

        with self._ws_lock:
            if self._ws is not None:
                try:
                    self._ws.close_connection()
                except Exception as exc:
                    logger.debug(f"WS close error (expected on stop): {exc}")

        if self._ws_thread is not None:
            self._ws_thread.join(timeout=10)
            if self._ws_thread.is_alive():
                logger.warning("WebSocket thread did not exit within 10 s.")
            else:
                logger.info("WebSocket thread stopped cleanly.")

        self._connected.clear()
        logger.info("LiveFeed stopped.")

    def get_latest_tick(self, symbol_token: str) -> Optional[Dict]:
        """
        Return the most recent tick received for a symbol token.

        Parameters
        ----------
        symbol_token : str
            The Angel One instrument token as a string (e.g. "26000").

        Returns
        -------
        dict or None
            Most recent normalised tick dict, or None if no tick has arrived.
        """
        with self._buffer_lock:
            buf = self._tick_buffers.get(str(symbol_token))
            if buf:
                return buf[-1]
        return None

    def get_tick_buffer(self, symbol_token: str) -> List[Dict]:
        """
        Return a list of the last ≤100 ticks for a given symbol token.

        Parameters
        ----------
        symbol_token : str

        Returns
        -------
        list[dict]  newest-last ordering
        """
        with self._buffer_lock:
            buf = self._tick_buffers.get(str(symbol_token))
            return list(buf) if buf else []

    @property
    def is_connected(self) -> bool:
        """True if the WebSocket is currently connected."""
        return self._connected.is_set()

    # ------------------------------------------------------------------
    # Internal: connection & reconnection logic
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """
        Main loop owned by the background WebSocket thread.

        Keeps trying to (re)connect until stop() is called, applying
        exponential back-off between attempts.
        """
        while self._running.is_set() and not self._stop_event.is_set():
            try:
                self._connect_ws()
                # _connect_ws blocks until the WS closes / errors
                if self._stop_event.is_set():
                    break
                # Unexpected disconnect — schedule reconnect
                logger.warning(
                    f"WebSocket disconnected. "
                    f"Reconnecting in {self._reconnect_delay:.1f}s "
                    f"(attempt {self._reconnect_attempts + 1}/{_MAX_RECONNECT_ATTEMPTS})…"
                )
                self._connected.clear()
                time.sleep(self._reconnect_delay)
                self._reconnect_attempts += 1
                self._reconnect_delay = min(
                    self._reconnect_delay * _RECONNECT_MULTIPLIER,
                    _RECONNECT_MAX_DELAY,
                )
                if self._reconnect_attempts >= _MAX_RECONNECT_ATTEMPTS:
                    logger.critical(
                        f"Exceeded {_MAX_RECONNECT_ATTEMPTS} reconnect attempts. "
                        "LiveFeed is shutting down."
                    )
                    self._running.clear()
                    break
            except Exception as exc:
                logger.error(f"Unexpected error in LiveFeed run loop: {exc}")
                if not self._stop_event.is_set():
                    time.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * _RECONNECT_MULTIPLIER,
                        _RECONNECT_MAX_DELAY,
                    )

    def _connect_ws(self) -> None:
        """
        Build a SmartWebSocket, wire up callbacks, and block until closed.
        """
        client_code = self._client.client_code
        feed_token  = self._client.feed_token
        api_key     = self._client.api_key

        logger.info(
            f"Opening SmartWebSocket (client={client_code}, "
            f"feed_token=…{feed_token[-6:] if feed_token else 'NONE'})…"
        )

        with self._ws_lock:
            self._ws = SmartWebSocket(
                auth_token=self._client.access_token,
                api_key=api_key,
                client_code=client_code,
                feed_token=feed_token,
            )

        # ----- Callback wiring -----
        def _on_open(ws):
            logger.info("SmartWebSocket connection opened.")
            self._connected.set()
            self._reconnect_delay = _RECONNECT_BASE_DELAY   # reset back-off
            self._reconnect_attempts = 0
            # Subscribe to all requested symbols
            try:
                ws.subscribe(
                    correlation_id="livefeed",
                    mode=2,          # MODE_QUOTE — includes OI, bid/ask
                    token_list=self._initial_symbols,
                )
                logger.info(
                    f"Subscribed to {len(self._initial_symbols)} instruments."
                )
            except Exception as exc:
                logger.error(f"Subscription error on open: {exc}")

        def _on_data(ws, message, data_type, continue_flag):
            self._handle_tick(data_type, message)

        def _on_error(ws, error):
            logger.error(f"SmartWebSocket error: {error}")
            self._connected.clear()

        def _on_close(ws):
            logger.warning("SmartWebSocket connection closed.")
            self._connected.clear()

        with self._ws_lock:
            self._ws.on_open    = _on_open
            self._ws.on_data    = _on_data
            self._ws.on_error   = _on_error
            self._ws.on_close   = _on_close

        # connect() is blocking — it runs the WS event loop until closed
        try:
            self._ws.connect()
        except Exception as exc:
            if self._stop_event.is_set():
                logger.debug("WS exception during intentional stop — ignoring.")
            else:
                logger.error(f"SmartWebSocket connect() raised: {exc}")
                raise

    # ------------------------------------------------------------------
    # Internal: tick handling
    # ------------------------------------------------------------------

    def _handle_tick(self, data_type: int, raw_message: Any) -> None:
        """
        Parse an incoming WebSocket message and dispatch to callback + buffer.

        Parameters
        ----------
        data_type   : int    WebSocket frame type (1 = text, 2 = binary)
        raw_message : Any    raw payload from SmartWebSocket
        """
        try:
            # SmartWebSocket passes already-decoded dicts for binary frames
            if isinstance(raw_message, (bytes, bytearray)):
                try:
                    raw_message = json.loads(raw_message.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return

            parsed = _parse_tick(raw_message)
            if parsed is None:
                return

            # SmartWebSocket may deliver list or single tick
            ticks: List[Dict] = parsed if isinstance(parsed, list) else [parsed]

            for tick in ticks:
                token = tick["token"]

                # Buffer update
                with self._buffer_lock:
                    if token not in self._tick_buffers:
                        self._tick_buffers[token] = deque(maxlen=_TICK_BUFFER_SIZE)
                    self._tick_buffers[token].append(tick)

                # User callback
                with self._callback_lock:
                    cb = self._callback
                if cb is not None:
                    try:
                        cb(tick)
                    except Exception as cb_exc:
                        logger.error(
                            f"Exception in tick callback for token {token}: {cb_exc}"
                        )

        except Exception as exc:
            logger.error(f"Error handling tick: {exc}")
