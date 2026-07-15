"""
Intraday Data Service - WebSocket-based live candle streaming

Streams real-time 1-minute and 5-minute OHLCV candles for Nifty50 and BankNifty
from Angel One SmartAPI WebSocket feed. Includes connection management, automatic
reconnection with exponential backoff, candle aggregation, and buffering.

Architecture:
- Uses LiveFeed for WebSocket connectivity and tick management
- Aggregates ticks into 1-min candles in real-time
- Resamples 1-min candles to 5-min candles
- Maintains rolling buffer of recent candles (configurable)
- Thread-safe access to candle data
- Broadcasts candle updates via callbacks
- Auto-reconnects on disconnection
"""

import asyncio
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, asdict

import pytz
from loguru import logger

from data.angel_client import AngelOneClient
from data.live_feed import LiveFeed


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IST = pytz.timezone("Asia/Kolkata")

# Angel One exchange types (for WebSocket subscription)
EXCHANGE_NSE = 1  # NSE Cash Market
EXCHANGE_NFO = 2  # NSE Futures & Options

# Instrument tokens (Angel One)
NIFTY_50_TOKEN = "99926000"      # Nifty 50 Index
BANKNIFTY_TOKEN = "99926009"     # Bank Nifty Index

# Symbol mapping
SYMBOL_NIFTY = "NIFTY"
SYMBOL_BANKNIFTY = "BANKNIFTY"

# Candle buffer sizes (number of candles to retain in memory)
DEFAULT_CANDLE_BUFFER_SIZE = 500  # ~8 hours of 1-min data
CANDLE_1MIN = "1min"
CANDLE_5MIN = "5min"

# Market hours (IST)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Candle:
    """OHLCV candle data structure"""
    timestamp: datetime     # Candle start time (IST-aware)
    symbol: str            # "NIFTY" or "BANKNIFTY"
    interval: str          # "1min" or "5min"
    open: float
    high: float
    low: float
    close: float
    volume: int
    tick_count: int = 0    # Number of ticks aggregated

    def to_dict(self) -> dict:
        """Convert to dictionary with ISO timestamp"""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


class CandleAggregator:
    """
    Aggregates real-time ticks into OHLCV candles.

    Maintains the current incomplete candle and emits completed candles
    when the interval boundary is crossed.
    """

    def __init__(self, symbol: str, interval: str):
        """
        Parameters
        ----------
        symbol : str
            Symbol name ("NIFTY" or "BANKNIFTY")
        interval : str
            Candle interval ("1min" or "5min")
        """
        self.symbol = symbol
        self.interval = interval
        self.interval_minutes = 1 if interval == CANDLE_1MIN else 5

        self.current_candle: Optional[Candle] = None
        self.lock = threading.Lock()

    def _get_candle_timestamp(self, tick_time: datetime) -> datetime:
        """
        Get the candle start timestamp for a given tick time.

        Rounds down to the nearest interval boundary.
        Example: 09:17:35 with 5min → 09:15:00
        """
        minute = (tick_time.minute // self.interval_minutes) * self.interval_minutes
        return tick_time.replace(minute=minute, second=0, microsecond=0)

    def add_tick(self, tick: Dict) -> Optional[Candle]:
        """
        Add a tick to the aggregator.

        Parameters
        ----------
        tick : dict
            Tick data with keys: timestamp, ltp, volume

        Returns
        -------
        Candle or None
            Returns the completed candle when interval boundary is crossed,
            None otherwise
        """
        with self.lock:
            tick_time = tick["timestamp"]
            candle_ts = self._get_candle_timestamp(tick_time)
            ltp = tick["ltp"]
            volume = tick["volume"]

            # Initialize new candle if needed
            if self.current_candle is None:
                self.current_candle = Candle(
                    timestamp=candle_ts,
                    symbol=self.symbol,
                    interval=self.interval,
                    open=ltp,
                    high=ltp,
                    low=ltp,
                    close=ltp,
                    volume=volume,
                    tick_count=1,
                )
                return None

            # Check if we've crossed into a new candle period
            if candle_ts > self.current_candle.timestamp:
                # Current candle is complete — emit it
                completed = self.current_candle

                # Start new candle
                self.current_candle = Candle(
                    timestamp=candle_ts,
                    symbol=self.symbol,
                    interval=self.interval,
                    open=ltp,
                    high=ltp,
                    low=ltp,
                    close=ltp,
                    volume=volume,
                    tick_count=1,
                )

                return completed

            # Update current candle
            self.current_candle.high = max(self.current_candle.high, ltp)
            self.current_candle.low = min(self.current_candle.low, ltp)
            self.current_candle.close = ltp
            self.current_candle.volume = volume  # Angel One sends cumulative volume
            self.current_candle.tick_count += 1

            return None

    def get_current_candle(self) -> Optional[Candle]:
        """Get the current incomplete candle (useful for live updates)"""
        with self.lock:
            return self.current_candle


class Candle5MinResampler:
    """
    Resamples 1-minute candles into 5-minute candles.

    Maintains a buffer of recent 1-min candles and emits a 5-min candle
    when 5 one-minute candles are accumulated for a 5-minute period.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.buffer: deque = deque(maxlen=10)  # Keep last 10 1-min candles
        self.lock = threading.Lock()

    def _get_5min_timestamp(self, dt: datetime) -> datetime:
        """Round down to nearest 5-minute boundary"""
        minute = (dt.minute // 5) * 5
        return dt.replace(minute=minute, second=0, microsecond=0)

    def add_1min_candle(self, candle_1min: Candle) -> Optional[Candle]:
        """
        Add a completed 1-minute candle.

        Returns
        -------
        Candle or None
            Returns a completed 5-min candle when boundary is crossed
        """
        with self.lock:
            self.buffer.append(candle_1min)

            # Get the 5-min boundary for the latest candle
            target_5min_ts = self._get_5min_timestamp(candle_1min.timestamp)

            # Collect all 1-min candles that belong to this 5-min period
            candles_in_period = [
                c for c in self.buffer
                if self._get_5min_timestamp(c.timestamp) == target_5min_ts
            ]

            # Check if we have the expected number of candles (5)
            # or if the next candle would belong to a different period
            expected_count = 5
            latest_minute = candle_1min.timestamp.minute

            # Emit 5-min candle if:
            # 1. We have 5 candles in this period, OR
            # 2. The period boundary is crossed (next minute % 5 == 0)
            next_minute = (latest_minute + 1) % 60
            is_period_complete = (next_minute % 5 == 0) or len(candles_in_period) >= expected_count

            if len(candles_in_period) > 0 and is_period_complete:
                # Build 5-min candle from aggregated 1-min candles
                candle_5min = Candle(
                    timestamp=target_5min_ts,
                    symbol=self.symbol,
                    interval=CANDLE_5MIN,
                    open=candles_in_period[0].open,
                    high=max(c.high for c in candles_in_period),
                    low=min(c.low for c in candles_in_period),
                    close=candles_in_period[-1].close,
                    volume=candles_in_period[-1].volume,  # Use latest cumulative volume
                    tick_count=sum(c.tick_count for c in candles_in_period),
                )

                return candle_5min

            return None


# ---------------------------------------------------------------------------
# Main Service
# ---------------------------------------------------------------------------

class IntradayDataService:
    """
    WebSocket-based intraday data streaming service.

    Subscribes to Nifty50 and BankNifty real-time ticks via Angel One SmartAPI,
    aggregates them into 1-min and 5-min candles, maintains rolling buffers,
    and broadcasts candle updates via callbacks.

    Features:
    - Auto-reconnection with exponential backoff
    - Thread-safe candle access
    - Multiple callback subscription support
    - Rolling candle buffers (configurable size)
    - Market hours awareness
    - Health monitoring

    Usage
    -----
    >>> client = AngelOneClient()
    >>> client.connect()
    >>> service = IntradayDataService(client)
    >>> service.subscribe_candles(my_callback)
    >>> service.start()
    >>> # ... trading operations ...
    >>> service.stop()
    """

    def __init__(
        self,
        client: AngelOneClient,
        candle_buffer_size: int = DEFAULT_CANDLE_BUFFER_SIZE,
    ):
        """
        Parameters
        ----------
        client : AngelOneClient
            Authenticated Angel One client instance
        candle_buffer_size : int
            Number of candles to retain in memory per symbol/interval
        """
        if not isinstance(client, AngelOneClient):
            raise TypeError("client must be an AngelOneClient instance")

        self.client = client
        self.candle_buffer_size = candle_buffer_size

        # Symbol configuration
        self.symbols = {
            SYMBOL_NIFTY: {
                "token": NIFTY_50_TOKEN,
                "exchange_type": EXCHANGE_NSE,
            },
            SYMBOL_BANKNIFTY: {
                "token": BANKNIFTY_TOKEN,
                "exchange_type": EXCHANGE_NSE,
            },
        }

        # WebSocket feed
        symbol_list = [
            {
                "token": cfg["token"],
                "exchange_type": cfg["exchange_type"],
            }
            for cfg in self.symbols.values()
        ]
        self.live_feed = LiveFeed(client, symbols=symbol_list)

        # Candle aggregators (1-min)
        self.aggregators_1min: Dict[str, CandleAggregator] = {
            SYMBOL_NIFTY: CandleAggregator(SYMBOL_NIFTY, CANDLE_1MIN),
            SYMBOL_BANKNIFTY: CandleAggregator(SYMBOL_BANKNIFTY, CANDLE_1MIN),
        }

        # 5-min resamplers
        self.resamplers_5min: Dict[str, Candle5MinResampler] = {
            SYMBOL_NIFTY: Candle5MinResampler(SYMBOL_NIFTY),
            SYMBOL_BANKNIFTY: Candle5MinResampler(SYMBOL_BANKNIFTY),
        }

        # Candle buffers: {symbol: {interval: deque}}
        self.candle_buffers: Dict[str, Dict[str, deque]] = {
            SYMBOL_NIFTY: {
                CANDLE_1MIN: deque(maxlen=candle_buffer_size),
                CANDLE_5MIN: deque(maxlen=candle_buffer_size // 5),
            },
            SYMBOL_BANKNIFTY: {
                CANDLE_1MIN: deque(maxlen=candle_buffer_size),
                CANDLE_5MIN: deque(maxlen=candle_buffer_size // 5),
            },
        }
        self.buffer_lock = threading.Lock()

        # Callback subscriptions
        self.candle_callbacks: List[Callable[[Candle], None]] = []
        self.callback_lock = threading.Lock()

        # Token → Symbol mapping for tick routing
        self.token_to_symbol = {
            NIFTY_50_TOKEN: SYMBOL_NIFTY,
            BANKNIFTY_TOKEN: SYMBOL_BANKNIFTY,
        }

        # Statistics
        self.stats = {
            "ticks_received": 0,
            "candles_1min_emitted": 0,
            "candles_5min_emitted": 0,
            "last_tick_time": None,
            "connection_started": None,
        }
        self.stats_lock = threading.Lock()

        logger.info(
            f"IntradayDataService initialized for {list(self.symbols.keys())} "
            f"with {candle_buffer_size} candle buffer size"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the WebSocket feed and begin streaming candles.

        Non-blocking: returns immediately after starting background threads.
        """
        logger.info("Starting IntradayDataService...")

        # Subscribe to tick callback
        self.live_feed.subscribe(callback=self._on_tick)

        # Start WebSocket feed
        self.live_feed.start()

        with self.stats_lock:
            self.stats["connection_started"] = datetime.now(IST)

        logger.success("IntradayDataService started successfully")

    def stop(self) -> None:
        """
        Stop the WebSocket feed and shut down the service.

        Blocks until graceful shutdown completes.
        """
        logger.info("Stopping IntradayDataService...")
        self.live_feed.stop()
        logger.success("IntradayDataService stopped")

    def subscribe_candles(self, callback: Callable[[Candle], None]) -> None:
        """
        Subscribe to candle updates.

        The callback is invoked whenever a new candle (1-min or 5-min) is completed.

        Parameters
        ----------
        callback : callable
            Function with signature: callback(candle: Candle) -> None
            Called from WebSocket thread — keep it fast or dispatch to another thread
        """
        if not callable(callback):
            raise TypeError("callback must be callable")

        with self.callback_lock:
            self.candle_callbacks.append(callback)

        logger.info(f"Candle callback registered (total: {len(self.candle_callbacks)})")

    def unsubscribe_candles(self, callback: Callable[[Candle], None]) -> None:
        """Remove a previously registered candle callback"""
        with self.callback_lock:
            if callback in self.candle_callbacks:
                self.candle_callbacks.remove(callback)
                logger.info(f"Candle callback unregistered (remaining: {len(self.candle_callbacks)})")

    def get_candles(
        self,
        symbol: str,
        interval: str,
        limit: Optional[int] = None,
    ) -> List[Candle]:
        """
        Retrieve buffered candles for a symbol and interval.

        Parameters
        ----------
        symbol : str
            "NIFTY" or "BANKNIFTY"
        interval : str
            "1min" or "5min"
        limit : int, optional
            Number of most recent candles to return (default: all)

        Returns
        -------
        list[Candle]
            List of candles, newest last
        """
        with self.buffer_lock:
            if symbol not in self.candle_buffers:
                return []
            if interval not in self.candle_buffers[symbol]:
                return []

            buffer = self.candle_buffers[symbol][interval]
            candles = list(buffer)

            if limit and limit > 0:
                candles = candles[-limit:]

            return candles

    def get_latest_candle(
        self,
        symbol: str,
        interval: str,
        include_incomplete: bool = False,
    ) -> Optional[Candle]:
        """
        Get the most recent candle for a symbol and interval.

        Parameters
        ----------
        symbol : str
            "NIFTY" or "BANKNIFTY"
        interval : str
            "1min" or "5min"
        include_incomplete : bool
            If True, returns the current incomplete candle if no complete candle exists

        Returns
        -------
        Candle or None
        """
        # Try to get the latest complete candle
        candles = self.get_candles(symbol, interval, limit=1)
        if candles:
            return candles[-1]

        # If no complete candle and incomplete is requested, get current candle
        if include_incomplete and interval == CANDLE_1MIN:
            aggregator = self.aggregators_1min.get(symbol)
            if aggregator:
                return aggregator.get_current_candle()

        return None

    def get_stats(self) -> Dict[str, Any]:
        """
        Get service statistics and health metrics.

        Returns
        -------
        dict
            Statistics including tick counts, candle counts, connection status
        """
        with self.stats_lock:
            stats = dict(self.stats)

        stats["is_connected"] = self.live_feed.is_connected
        stats["symbols"] = list(self.symbols.keys())

        # Add buffer sizes
        with self.buffer_lock:
            stats["buffer_sizes"] = {
                symbol: {
                    interval: len(self.candle_buffers[symbol][interval])
                    for interval in [CANDLE_1MIN, CANDLE_5MIN]
                }
                for symbol in self.symbols.keys()
            }

        return stats

    def is_market_hours(self, dt: Optional[datetime] = None) -> bool:
        """
        Check if the given time is within market hours (9:15 AM - 3:30 PM IST).

        Parameters
        ----------
        dt : datetime, optional
            Time to check (default: now)

        Returns
        -------
        bool
        """
        if dt is None:
            dt = datetime.now(IST)

        # Ensure timezone awareness
        if dt.tzinfo is None:
            dt = IST.localize(dt)
        else:
            dt = dt.astimezone(IST)

        # Check if it's a weekday (Monday=0, Sunday=6)
        if dt.weekday() >= 5:  # Saturday or Sunday
            return False

        market_open = dt.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
        market_close = dt.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)

        return market_open <= dt <= market_close

    # ------------------------------------------------------------------
    # Internal: tick processing
    # ------------------------------------------------------------------

    def _on_tick(self, tick: Dict) -> None:
        """
        Callback invoked by LiveFeed for each incoming tick.

        Routes tick to appropriate symbol aggregator and handles candle completion.
        """
        try:
            token = tick.get("token")
            symbol = self.token_to_symbol.get(token)

            if not symbol:
                # Unknown token — skip
                return

            # Update statistics
            with self.stats_lock:
                self.stats["ticks_received"] += 1
                self.stats["last_tick_time"] = tick["timestamp"]

            # Process 1-min candle
            aggregator = self.aggregators_1min.get(symbol)
            if aggregator:
                completed_1min = aggregator.add_tick(tick)

                if completed_1min:
                    # Store 1-min candle
                    with self.buffer_lock:
                        self.candle_buffers[symbol][CANDLE_1MIN].append(completed_1min)

                    with self.stats_lock:
                        self.stats["candles_1min_emitted"] += 1

                    logger.debug(
                        f"[{symbol}] 1-min candle complete: "
                        f"{completed_1min.timestamp.strftime('%H:%M')} "
                        f"O:{completed_1min.open:.2f} H:{completed_1min.high:.2f} "
                        f"L:{completed_1min.low:.2f} C:{completed_1min.close:.2f} "
                        f"ticks:{completed_1min.tick_count}"
                    )

                    # Broadcast 1-min candle
                    self._broadcast_candle(completed_1min)

                    # Process 5-min resampling
                    resampler = self.resamplers_5min.get(symbol)
                    if resampler:
                        completed_5min = resampler.add_1min_candle(completed_1min)

                        if completed_5min:
                            # Store 5-min candle
                            with self.buffer_lock:
                                self.candle_buffers[symbol][CANDLE_5MIN].append(completed_5min)

                            with self.stats_lock:
                                self.stats["candles_5min_emitted"] += 1

                            logger.info(
                                f"[{symbol}] 5-min candle complete: "
                                f"{completed_5min.timestamp.strftime('%H:%M')} "
                                f"O:{completed_5min.open:.2f} H:{completed_5min.high:.2f} "
                                f"L:{completed_5min.low:.2f} C:{completed_5min.close:.2f}"
                            )

                            # Broadcast 5-min candle
                            self._broadcast_candle(completed_5min)

        except Exception as exc:
            logger.error(f"Error processing tick: {exc}", exc_info=True)

    def _broadcast_candle(self, candle: Candle) -> None:
        """Invoke all registered candle callbacks"""
        with self.callback_lock:
            callbacks = list(self.candle_callbacks)

        for callback in callbacks:
            try:
                callback(candle)
            except Exception as exc:
                logger.error(
                    f"Error in candle callback: {exc}",
                    exc_info=True,
                )


# ---------------------------------------------------------------------------
# Async wrapper for FastAPI integration
# ---------------------------------------------------------------------------

class AsyncIntradayDataService:
    """
    Async wrapper around IntradayDataService for FastAPI WebSocket broadcasting.

    Provides async methods for integration with FastAPI endpoints and
    broadcasts candles to connected WebSocket clients.
    """

    def __init__(self, service: IntradayDataService):
        """
        Parameters
        ----------
        service : IntradayDataService
            The underlying synchronous service
        """
        self.service = service
        self.broadcast_queue: asyncio.Queue = None
        self.broadcast_task: asyncio.Task = None

    async def start(self, websocket_manager=None):
        """
        Start the service and async broadcast loop.

        Parameters
        ----------
        websocket_manager : WebSocketManager, optional
            Manager to broadcast candles to connected WebSocket clients
        """
        # Start the underlying service
        self.service.start()

        # Set up async broadcasting if websocket_manager is provided
        if websocket_manager:
            self.broadcast_queue = asyncio.Queue()

            def sync_callback(candle: Candle):
                """Thread-safe callback that puts candles into async queue"""
                try:
                    asyncio.get_event_loop().call_soon_threadsafe(
                        self.broadcast_queue.put_nowait,
                        candle,
                    )
                except Exception as exc:
                    logger.error(f"Error queueing candle for broadcast: {exc}")

            self.service.subscribe_candles(sync_callback)

            # Start broadcast loop
            self.broadcast_task = asyncio.create_task(
                self._broadcast_loop(websocket_manager)
            )

            logger.info("AsyncIntradayDataService started with WebSocket broadcasting")

    async def stop(self):
        """Stop the service and broadcast loop"""
        if self.broadcast_task:
            self.broadcast_task.cancel()
            try:
                await self.broadcast_task
            except asyncio.CancelledError:
                pass

        self.service.stop()
        logger.info("AsyncIntradayDataService stopped")

    async def _broadcast_loop(self, websocket_manager):
        """Async loop that broadcasts candles to WebSocket clients"""
        try:
            while True:
                candle = await self.broadcast_queue.get()

                # Broadcast to all connected WebSocket clients
                await websocket_manager.broadcast({
                    "type": "candle_update",
                    "data": candle.to_dict(),
                })

        except asyncio.CancelledError:
            logger.info("Broadcast loop cancelled")
            raise
        except Exception as exc:
            logger.error(f"Error in broadcast loop: {exc}", exc_info=True)

    def get_candles(self, symbol: str, interval: str, limit: Optional[int] = None) -> List[Dict]:
        """Get candles as dictionaries (async-safe)"""
        candles = self.service.get_candles(symbol, interval, limit)
        return [c.to_dict() for c in candles]

    def get_latest_candle(self, symbol: str, interval: str) -> Optional[Dict]:
        """Get latest candle as dictionary (async-safe)"""
        candle = self.service.get_latest_candle(symbol, interval)
        return candle.to_dict() if candle else None

    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics (async-safe)"""
        return self.service.get_stats()
