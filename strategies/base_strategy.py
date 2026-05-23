"""
Abstract base strategy for the Nifty50 intraday options trading system.

All concrete strategies must inherit from BaseStrategy and implement
generate_signal() and should_exit(). The TradeSignal dataclass carries
all information needed by the order manager to execute a trade.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import pandas as pd
import pytz
from loguru import logger


IST = pytz.timezone("Asia/Kolkata")


@dataclass
class TradeSignal:
    """
    Unified trade signal produced by any strategy.

    Fields
    ------
    action          : one of BUY_CE | BUY_PE | SELL_CE | SELL_PE |
                      SELL_STRADDLE | SELL_STRANGLE | EXIT | NO_TRADE
    symbol          : Angel One tradingsymbol e.g. "NIFTY23MAY18300CE"
    token           : Angel One instrument token string e.g. "35227"
    exchange        : "NFO"
    qty             : total quantity in shares (lots × lot_size)
    transaction_type: "BUY" or "SELL"
    order_type      : "MARKET" or "LIMIT"
    price           : limit price (0.0 for MARKET orders)
    strike          : integer strike price e.g. 18300
    option_type     : "CE" or "PE"
    expiry          : expiry date string e.g. "25-MAY-2023"
    confidence      : model / rule confidence [0.0 – 1.0]
    strategy_name   : name of the strategy that generated this signal
    reasons         : list of human-readable reasons for the signal
    sl_price        : stop-loss price on the option premium
    target_price    : target price on the option premium
    timestamp       : UTC-aware (or naive) signal generation time
    """

    action: str
    symbol: str
    token: str
    exchange: str
    qty: int
    transaction_type: str
    order_type: str
    price: float
    strike: int
    option_type: str
    expiry: str
    confidence: float
    strategy_name: str
    reasons: list
    sl_price: float
    target_price: float
    timestamp: datetime = field(default_factory=datetime.now)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def is_actionable(self) -> bool:
        """True for any signal that requires actual order placement."""
        return self.action not in ("NO_TRADE", "EXIT")

    @property
    def is_buy(self) -> bool:
        return self.transaction_type == "BUY"

    @property
    def is_sell(self) -> bool:
        return self.transaction_type == "SELL"

    def __str__(self) -> str:
        return (
            f"TradeSignal({self.action} | {self.symbol} | qty={self.qty} | "
            f"price={self.price:.2f} | SL={self.sl_price:.2f} | "
            f"target={self.target_price:.2f} | conf={self.confidence:.2f} | "
            f"strategy={self.strategy_name})"
        )


def _no_trade(strategy_name: str, reason: str = "No signal") -> TradeSignal:
    """Convenience factory for a NO_TRADE signal."""
    return TradeSignal(
        action="NO_TRADE",
        symbol="",
        token="",
        exchange="NFO",
        qty=0,
        transaction_type="BUY",
        order_type="MARKET",
        price=0.0,
        strike=0,
        option_type="",
        expiry="",
        confidence=0.0,
        strategy_name=strategy_name,
        reasons=[reason],
        sl_price=0.0,
        target_price=0.0,
    )


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Parameters
    ----------
    config : dict
        Full application configuration loaded from config/config.yaml.
    name : str
        Human-readable strategy identifier (used in logs and signals).
    """

    def __init__(self, config: dict, name: str) -> None:
        self.config: dict = config
        self.name: str = name
        self.trading_cfg: dict = config.get("trading", {})
        self.risk_cfg: dict = config.get("risk", {})
        self.strategy_cfg: dict = config.get("strategies", {})
        logger.info(f"Strategy initialised: {self.name}")

    # ------------------------------------------------------------------
    # Abstract interface – subclasses must implement both
    # ------------------------------------------------------------------

    @abstractmethod
    def generate_signal(
        self,
        df: pd.DataFrame,
        market_data: dict,
        options_data: dict,
    ) -> TradeSignal:
        """
        Analyse current market state and emit a TradeSignal.

        Parameters
        ----------
        df           : OHLCV DataFrame with pre-computed technical indicators.
                       Expected columns (minimum):
                         open, high, low, close, volume,
                         ema_9, ema_21, rsi, macd_hist,
                         vwap, atr, adx, supertrend, supertrend_direction
        market_data  : dict – live snapshot e.g.
                         {'spot_price': 18450.0, 'pcr': 1.1, 'iv': 14.5, ...}
        options_data : dict – option chain snapshot keyed by strike e.g.
                         {18400: {'CE': {'ltp': 85.0, 'iv': 14.2, ...},
                                  'PE': {'ltp': 55.0, 'iv': 15.1, ...}}}

        Returns
        -------
        TradeSignal
        """
        ...

    @abstractmethod
    def should_exit(
        self,
        position: dict,
        current_data: dict,
    ) -> tuple[bool, str]:
        """
        Decide whether an open position should be closed.

        Parameters
        ----------
        position     : dict – internal position book entry.
                         Keys: symbol, token, entry_price, current_price, qty,
                               direction, sl_price, target_price,
                               entry_time, strategy, ...
        current_data : dict – live market snapshot at decision time.
                         Keys: ltp, spot_price, timestamp, df (OHLCV DataFrame), ...

        Returns
        -------
        (should_exit: bool, reason: str)
        """
        ...

    # ------------------------------------------------------------------
    # Common helpers available to all subclasses
    # ------------------------------------------------------------------

    def get_lot_size(self) -> int:
        """Return Nifty lot size from config (default 50)."""
        return int(self.trading_cfg.get("lot_size", 50))

    def is_trading_hours(self) -> bool:
        """
        Return True only between 09:20 and 15:00 IST (inclusive).
        Prevents strategies from generating signals outside active window.
        """
        now_ist = datetime.now(IST)
        start_h, start_m = 9, 20
        end_h, end_m = 15, 0
        total_now = now_ist.hour * 60 + now_ist.minute
        total_start = start_h * 60 + start_m
        total_end = end_h * 60 + end_m
        in_window = total_start <= total_now <= total_end
        if not in_window:
            logger.debug(
                f"[{self.name}] Outside trading hours "
                f"({now_ist.strftime('%H:%M')} IST). No signal generated."
            )
        return in_window

    def _get_atm_strike(self, spot_price: float, strike_step: int = 50) -> int:
        """Round spot price to the nearest valid Nifty strike."""
        return int(round(spot_price / strike_step) * strike_step)

    def _get_otm_strike(
        self,
        spot_price: float,
        option_type: str,
        levels: int = 1,
        strike_step: int = 50,
    ) -> int:
        """
        Return an OTM strike n levels away from ATM.

        For CE: OTM is higher than spot.
        For PE: OTM is lower than spot.
        """
        atm = self._get_atm_strike(spot_price, strike_step)
        if option_type.upper() == "CE":
            return atm + levels * strike_step
        return atm - levels * strike_step

    def _has_minimum_rows(self, df: pd.DataFrame, min_rows: int = 20) -> bool:
        """Check DataFrame has enough rows for indicator calculation."""
        if df is None or len(df) < min_rows:
            logger.warning(
                f"[{self.name}] Insufficient data: "
                f"{0 if df is None else len(df)} rows (need {min_rows})."
            )
            return False
        return True

    def _required_columns_present(
        self, df: pd.DataFrame, required: list[str]
    ) -> bool:
        """Verify all required indicator columns exist in the DataFrame."""
        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.warning(
                f"[{self.name}] Missing columns in DataFrame: {missing}"
            )
            return False
        return True

    def _log_signal(self, signal: TradeSignal) -> None:
        if signal.action == "NO_TRADE":
            logger.debug(
                f"[{self.name}] NO_TRADE | reason: {signal.reasons[0] if signal.reasons else 'n/a'}"
            )
        else:
            logger.info(f"[{self.name}] Signal → {signal}")
