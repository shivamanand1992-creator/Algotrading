"""
Angel One SmartAPI authenticated client.

Handles authentication, session management, market data retrieval,
order management, and historical data fetching for the Nifty50 intraday
options trading system.
"""

import os
import time
import json
import yaml
import pyotp
import threading
import functools
import pandas as pd
import pytz
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

try:
    from SmartApi import SmartConnect
except ImportError as e:
    logger.error(f"SmartApi package not found. Install with: pip install smartapi-python  [{e}]")
    raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_env(value: str) -> str:
    """Expand ${VAR} placeholders in YAML values using real env vars."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        var_name = value[2:-1]
        return os.environ.get(var_name, "")
    return value


def _retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Decorator that retries a method on exception with exponential backoff."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            wait = delay
            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    attempt += 1
                    if attempt >= max_attempts:
                        logger.error(
                            f"[{func.__name__}] Failed after {max_attempts} attempts: {exc}"
                        )
                        raise
                    logger.warning(
                        f"[{func.__name__}] Attempt {attempt}/{max_attempts} failed: {exc}. "
                        f"Retrying in {wait:.1f}s…"
                    )
                    time.sleep(wait)
                    wait *= backoff
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Main client class
# ---------------------------------------------------------------------------

class AngelOneClient:
    """
    Authenticated wrapper around Angel One SmartAPI.

    Loads credentials from config/config.yaml and .env, authenticates via
    SmartConnect with TOTP, and exposes methods for profile, funds,
    positions, orders, market data, and order management.

    Session tokens are auto-refreshed every 6 hours in a background thread.
    All public methods are wrapped with 3-attempt retry logic.
    """

    _SESSION_REFRESH_INTERVAL_HOURS: int = 6

    def __init__(self, config: dict = None) -> None:
        if config is None:
            config_path = _PROJECT_ROOT / "config" / "config.yaml"
            with open(config_path, "r") as fh:
                config = yaml.safe_load(fh)

        broker_cfg = config.get("broker", {})

        self.api_key: str       = _resolve_env(broker_cfg.get("api_key", ""))
        self.client_code: str   = _resolve_env(broker_cfg.get("client_code", ""))
        self.password: str      = _resolve_env(broker_cfg.get("password", ""))
        self.totp_secret: str   = _resolve_env(broker_cfg.get("totp_secret", ""))
        self.base_url: str      = broker_cfg.get("base_url", "https://apiconnect.angelone.in")

        self._smart: SmartConnect | None = None
        self.access_token: str  = ""
        self.feed_token: str    = ""
        self.refresh_token: str = ""
        self._session_lock      = threading.Lock()
        self._refresh_timer: threading.Timer | None = None

        logger.info("AngelOneClient initialised (not yet connected).")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Authenticate with Angel One SmartAPI using client_code, password,
        and a time-based OTP generated from the TOTP secret.

        Populates self.access_token, self.feed_token, self.refresh_token
        and schedules automatic token refresh every 6 hours.
        """
        logger.info("Connecting to Angel One SmartAPI…")
        with self._session_lock:
            self._smart = SmartConnect(api_key=self.api_key)
            totp_value = pyotp.TOTP(self.totp_secret).now()
            data = self._smart.generateSession(
                self.client_code, self.password, totp_value
            )
            if data.get("status") is False:
                raise ConnectionError(
                    f"SmartAPI login failed: {data.get('message', 'unknown error')}"
                )
            tokens = data.get("data", {})
            self.access_token  = tokens.get("jwtToken", "")
            self.feed_token    = tokens.get("feedToken", "")
            self.refresh_token = tokens.get("refreshToken", "")
            logger.success(
                f"Connected. access_token=…{self.access_token[-6:]}, "
                f"feed_token=…{self.feed_token[-6:]}"
            )
        self._schedule_token_refresh()

    def _refresh_session(self) -> None:
        """Silently refresh the JWT using the refresh token."""
        logger.info("Auto-refreshing Angel One session token…")
        with self._session_lock:
            try:
                data = self._smart.generateToken(self.refresh_token)
                if not isinstance(data, dict):
                    raise RuntimeError(
                        f"generateToken returned {type(data).__name__}: {str(data)[:120]}"
                    )
                if data.get("status") is False:
                    logger.warning(
                        "Token refresh returned failure; attempting full re-login."
                    )
                    self.connect()
                    return
                tokens = data.get("data", {})
                self.access_token  = tokens.get("jwtToken", self.access_token)
                self.feed_token    = tokens.get("feedToken", self.feed_token)
                self.refresh_token = tokens.get("refreshToken", self.refresh_token)
                logger.success("Session token refreshed successfully.")
            except Exception as exc:
                logger.error(f"Token refresh failed: {exc}. Attempting full re-login.")
                try:
                    self.connect()
                except Exception as reconnect_exc:
                    logger.critical(f"Full re-login also failed: {reconnect_exc}")
        self._schedule_token_refresh()

    def _schedule_token_refresh(self) -> None:
        """Schedule the next token refresh via a daemon thread timer."""
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
        interval_seconds = self._SESSION_REFRESH_INTERVAL_HOURS * 3600
        self._refresh_timer = threading.Timer(
            interval_seconds, self._refresh_session
        )
        self._refresh_timer.daemon = True
        self._refresh_timer.start()
        logger.debug(
            f"Next session refresh scheduled in "
            f"{self._SESSION_REFRESH_INTERVAL_HOURS}h."
        )

    def disconnect(self) -> None:
        """Terminate the SmartAPI session and cancel the refresh timer."""
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
        if self._smart is not None:
            try:
                self._smart.terminateSession(self.client_code)
                logger.info("SmartAPI session terminated.")
            except Exception as exc:
                logger.warning(f"Error terminating session: {exc}")

    def _ensure_connected(self) -> None:
        if self._smart is None or not self.access_token:
            raise RuntimeError(
                "AngelOneClient is not connected. Call connect() first."
            )

    # ------------------------------------------------------------------
    # Account information
    # ------------------------------------------------------------------

    @_retry(max_attempts=3)
    def get_profile(self) -> dict:
        """Return user profile dict from Angel One."""
        self._ensure_connected()
        logger.debug("Fetching user profile.")
        resp = self._smart.getProfile(self.refresh_token)
        _assert_ok(resp, "getProfile")
        return resp.get("data", {})

    @_retry(max_attempts=3)
    def get_funds(self) -> dict:
        """Return available funds / RMS limits."""
        self._ensure_connected()
        logger.debug("Fetching funds.")
        resp = self._smart.rmsLimit()
        _assert_ok(resp, "rmsLimit")
        return resp.get("data", {})

    @_retry(max_attempts=3)
    def get_positions(self) -> list[dict]:
        """Return list of current open positions."""
        self._ensure_connected()
        logger.debug("Fetching positions.")
        resp = self._smart.position()
        _assert_ok(resp, "position")
        return resp.get("data", []) or []

    @_retry(max_attempts=3)
    def get_orders(self) -> list[dict]:
        """Return today's order book."""
        self._ensure_connected()
        logger.debug("Fetching order book.")
        resp = self._smart.orderBook()
        _assert_ok(resp, "orderBook")
        return resp.get("data", []) or []

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    @_retry(max_attempts=3)
    def get_ltp(self, exchange: str, symbol: str, token: str) -> float:
        """
        Fetch Last Traded Price for a single instrument.

        Parameters
        ----------
        exchange : str  e.g. "NSE", "NFO"
        symbol   : str  e.g. "NIFTY"
        token    : str  Angel One instrument token e.g. "26000"

        Returns
        -------
        float  last traded price
        """
        self._ensure_connected()
        logger.debug(f"get_ltp: {exchange}:{symbol} token={token}")
        resp = self._smart.ltpData(exchange, symbol, token)
        _assert_ok(resp, "ltpData")
        ltp = resp.get("data", {}).get("ltp", 0.0)
        logger.debug(f"LTP [{symbol}] = {ltp}")
        return float(ltp)

    def search_scrip(self, exchange: str, symbol: str) -> Optional[str]:
        """
        Resolve the Angel One instrument token for a cash equity symbol.

        Parameters
        ----------
        exchange : str  e.g. "NSE"
        symbol   : str  trading symbol e.g. "RELIANCE"

        Returns
        -------
        str  instrument token, or None if not found / client not connected
        """
        if self._smart is None:
            return None
        try:
            result = self._smart.searchScrip(exchange, symbol)
            if result and result.get("status"):
                # NSE cash equity trading symbols are "SYMBOL-EQ"; match that first,
                # then fall back to exact match for any other exchange formats.
                eq_symbol = f"{symbol.upper()}-EQ"
                exact     = symbol.upper()
                token = None
                for item in result.get("data", []):
                    ts = str(item.get("tradingsymbol", "")).upper()
                    # Angel One returns "symboltoken" (not "token") for equity scrips
                    tok = item.get("symboltoken") or item.get("token")
                    if not tok:
                        continue
                    if ts == eq_symbol:
                        token = str(tok)
                        break
                    if ts == exact and token is None:
                        token = str(tok)
                if token:
                    logger.debug(f"searchScrip: {symbol} → token={token}")
                    return token
        except Exception as exc:
            logger.warning(f"searchScrip({exchange}, {symbol}) failed: {exc}")
        return None

    @_retry(max_attempts=3)
    def get_option_chain(
        self,
        symbol: str,
        expiry: str,
        strike_price: float,
        n_strikes: int = 10,
    ) -> dict:
        """
        Fetch the full options chain for a given symbol and expiry.

        Parameters
        ----------
        symbol        : str    e.g. "NIFTY"
        expiry        : str    "DD-MMM-YYYY" e.g. "25-MAY-2023"
        strike_price  : float  central strike (usually ATM)
        n_strikes     : int    number of strikes on each side of ATM

        Returns
        -------
        dict   raw API response data
        """
        self._ensure_connected()
        logger.info(
            f"Fetching option chain: {symbol} expiry={expiry} "
            f"strike={strike_price} n_strikes=±{n_strikes}"
        )
        resp = self._smart.optionChain(
            optionChainReq={
                "name": symbol,
                "expirydate": expiry,
                "strikeprice": str(int(strike_price)),
                "optiontype": "CE",
            }
        )
        # SmartAPI returns full chain; caller is expected to filter
        _assert_ok(resp, "optionChain")
        data = resp.get("data", {})
        logger.debug(
            f"Option chain fetched: {len(data.get('fetched', []))} records"
        )
        return data

    @_retry(max_attempts=3)
    def get_historical_data(
        self,
        exchange: str,
        symbol_token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV candle data and return as a tidy DataFrame.

        Parameters
        ----------
        exchange      : str  "NSE" | "NFO" | "BSE"
        symbol_token  : str  Angel One instrument token e.g. "26000"
        interval      : str  "ONE_MINUTE" | "THREE_MINUTE" | "FIVE_MINUTE" |
                             "TEN_MINUTE" | "FIFTEEN_MINUTE" | "THIRTY_MINUTE" |
                             "ONE_HOUR" | "ONE_DAY"
        from_date     : str  "YYYY-MM-DD HH:MM"
        to_date       : str  "YYYY-MM-DD HH:MM"

        Returns
        -------
        pd.DataFrame  columns: timestamp, open, high, low, close, volume
        """
        self._ensure_connected()
        logger.info(
            f"Historical data: {exchange}/{symbol_token} "
            f"interval={interval} [{from_date} → {to_date}]"
        )
        params = {
            "exchange":    exchange,
            "symboltoken": symbol_token,
            "interval":    interval,
            "fromdate":    from_date,
            "todate":      to_date,
        }
        resp = self._smart.getCandleData(params)
        _assert_ok(resp, "getCandleData")
        candles = resp.get("data", []) or []

        if not candles:
            logger.warning("No candle data returned from API.")
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
        df.sort_values("timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        logger.info(f"Historical data: {len(df)} candles returned.")
        return df

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    @_retry(max_attempts=3)
    def place_order(
        self,
        variety: str,
        exchange: str,
        symbol: str,
        token: str,
        qty: int,
        order_type: str,
        transaction_type: str,
        price: float = 0.0,
        trigger_price: float = 0.0,
        product: str = "INTRADAY",
    ) -> str:
        """
        Place an order and return the order_id string.

        Parameters
        ----------
        variety          : "NORMAL" | "STOPLOSS" | "AMO" | "ROBO"
        exchange         : "NSE" | "NFO" | "BSE"
        symbol           : tradingsymbol e.g. "NIFTY23MAY18300CE"
        token            : instrument token e.g. "35227"
        qty              : number of shares/lots (use lot_size-adjusted int)
        order_type       : "MARKET" | "LIMIT" | "STOPLOSS_LIMIT" | "STOPLOSS_MARKET"
        transaction_type : "BUY" | "SELL"
        price            : limit price (0 for MARKET)
        trigger_price    : stop trigger price (0 if unused)
        product          : "INTRADAY" | "DELIVERY" | "CARRYFORWARD" | "MARGIN"

        Returns
        -------
        str  order_id from Angel One
        """
        self._ensure_connected()
        order_params = {
            "variety":         variety,
            "exchange":        exchange,
            "tradingsymbol":   symbol,
            "symboltoken":     token,
            "transactiontype": transaction_type,
            "ordertype":       order_type,
            "producttype":     product,
            "duration":        "DAY",
            "price":           str(price),
            "triggerprice":    str(trigger_price),
            "squareoff":       "0",
            "stoploss":        "0",
            "quantity":        str(qty),
        }
        logger.info(
            f"Placing order: {transaction_type} {qty}x {symbol} "
            f"@ {price} [{order_type}/{variety}]"
        )
        # SmartConnect.placeOrder() does resp['data']['orderid'] directly and crashes
        # when Angel One returns an error with data as a string. Bypass it and use
        # _postRequest directly so we control response parsing.
        resp = self._smart._postRequest("api.order.place", order_params)
        _assert_ok(resp, "placeOrder")
        data = resp.get("data") or {}
        order_id = data if isinstance(data, str) else str(data.get("orderid", ""))
        if not order_id:
            raise RuntimeError(f"placeOrder: order_id empty in response: {resp}")
        logger.success(f"Order placed successfully. order_id={order_id}")
        return order_id

    @_retry(max_attempts=3)
    def modify_order(
        self,
        order_id: str,
        variety: str,
        qty: int,
        price: float,
        order_type: str,
        trigger_price: float = 0.0,
    ) -> str:
        """
        Modify an existing open order.

        Parameters
        ----------
        order_id      : str   returned by place_order
        variety       : str   same as in place_order
        qty           : int   updated quantity
        price         : float updated limit price
        order_type    : str   updated order type
        trigger_price : float updated stop trigger price

        Returns
        -------
        str  order_id (same as input on success)
        """
        self._ensure_connected()
        modify_params = {
            "variety":      variety,
            "orderid":      order_id,
            "ordertype":    order_type,
            "producttype":  "INTRADAY",
            "duration":     "DAY",
            "price":        str(price),
            "quantity":     str(qty),
            "triggerprice": str(trigger_price),
        }
        logger.info(
            f"Modifying order {order_id}: qty={qty} price={price} "
            f"type={order_type}"
        )
        resp = self._smart.modifyOrder(modify_params)
        _assert_ok(resp, "modifyOrder")
        modified_id = str(resp.get("data", {}).get("orderid", order_id))
        logger.success(f"Order modified. order_id={modified_id}")
        return modified_id

    @_retry(max_attempts=3)
    def cancel_order(self, order_id: str, variety: str = "NORMAL") -> bool:
        """
        Cancel an open order.

        Parameters
        ----------
        order_id : str  order to cancel
        variety  : str  order variety (default NORMAL)

        Returns
        -------
        bool  True if cancellation succeeded
        """
        self._ensure_connected()
        logger.info(f"Cancelling order {order_id} (variety={variety}).")
        resp = self._smart.cancelOrder(order_id, variety)
        _assert_ok(resp, "cancelOrder")
        logger.success(f"Order {order_id} cancelled.")
        return True

    @_retry(max_attempts=3)
    def get_order_status(self, order_id: str) -> dict:
        """
        Return the current status dict for a specific order.

        Scans today's order book and returns the matching entry.
        Raises KeyError if the order_id is not found.
        """
        self._ensure_connected()
        logger.debug(f"Fetching status for order {order_id}.")
        orders = self.get_orders()
        for order in orders:
            if str(order.get("orderid", "")) == str(order_id):
                logger.debug(
                    f"Order {order_id} status: {order.get('status', 'UNKNOWN')}"
                )
                return order
        raise KeyError(f"Order {order_id} not found in today's order book.")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _assert_ok(response, api_name: str) -> None:
    """
    Raise a RuntimeError if the Angel One API response indicates failure.

    Angel One returns {"status": true/false, "message": "...", "data": ...}.
    """
    if response is None:
        raise RuntimeError(f"{api_name}: received None response from API.")
    if not isinstance(response, dict):
        raise RuntimeError(
            f"{api_name}: expected dict response, got {type(response).__name__}: "
            f"{str(response)[:120]}"
        )
    if response.get("status") is False:
        msg = response.get("message", "No error message provided.")
        raise RuntimeError(f"{api_name} API error: {msg}")
