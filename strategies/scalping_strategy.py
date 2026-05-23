"""
Scalping Strategy for Nifty50 Intraday Options.

Uses 1-minute candles for entry triggers and 5-minute candles for
support/resistance context.  Targets quick 15-20 point moves on option
premium from intraday S/R bounces with volume confirmation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import pytz
from loguru import logger

from strategies.base_strategy import BaseStrategy, TradeSignal, _no_trade

IST = pytz.timezone("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REQUIRED_COLS_1MIN  = ["open", "high", "low", "close", "volume", "rsi"]
_REQUIRED_COLS_5MIN  = ["high", "low"]
_MIN_ROWS_1MIN       = 15
_MIN_ROWS_5MIN       = 20

_VOLUME_CONFIRMATION_MULTIPLIER = 1.5   # current volume ≥ 1.5× average
_VOLUME_LOOKBACK                = 10    # bars to compute average volume
_SR_PROXIMITY_PCT               = 0.15  # price must be within 0.15 % of S/R
_QUICK_TARGET_POINTS            = 17.5  # midpoint of 15-20 point target range
_RSI_BOUNCE_MIN                 = 45    # RSI floor for CE entry
_RSI_BOUNCE_MAX                 = 55    # RSI ceiling for PE entry
_RSI_BULL_MIN                   = 45    # broader bull confirmation
_RSI_BEAR_MAX                   = 55    # broader bear confirmation


class ScalpingStrategy(BaseStrategy):
    """
    1–2 minute scalping strategy using intraday S/R levels.

    Entry logic (1min chart + 5min S/R):
        BUY_CE:
            • Close is within SR_PROXIMITY_PCT % of the 5min support level
            • Current 1min candle is bullish (close > open)
            • RSI on 1min chart > RSI_BOUNCE_MIN (45) — avoiding oversold exhaustion
            • Current bar volume ≥ 1.5× average of last 10 bars (volume confirmation)

        BUY_PE:
            • Close is within SR_PROXIMITY_PCT % of the 5min resistance level
            • Current 1min candle is bearish (close < open)
            • RSI on 1min chart < RSI_BOUNCE_MAX (55)
            • Current bar volume ≥ 1.5× average of last 10 bars

    Exit logic:
        • Target: option premium gains QUICK_TARGET_POINTS
        • SL: option premium drops by option_buy_sl_pct (30 %)
        • Max hold: 15 minutes (scalp horizon)
        • Time-based: 15:20 IST hard cut-off
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config, name="Scalping")

        strat_cfg = self.strategy_cfg.get("scalping", {})
        risk_cfg  = self.risk_cfg

        self.sr_lookback: int   = int(strat_cfg.get("support_resistance_lookback", 20))
        self.sl_pct:      float = float(risk_cfg.get("option_buy_sl_pct", 0.30))
        # Target: fixed point gain on option premium, not %-based
        self.target_points: float = _QUICK_TARGET_POINTS
        self.max_hold_minutes: int = 15

        logger.info(
            f"[{self.name}] Config — SR_lookback={self.sr_lookback}, "
            f"volume_mult={_VOLUME_CONFIRMATION_MULTIPLIER}x, "
            f"target_pts={self.target_points}, SL={self.sl_pct*100:.0f}%, "
            f"max_hold={self.max_hold_minutes}min"
        )

    # ------------------------------------------------------------------
    # Primary signal generation
    # ------------------------------------------------------------------

    def generate_signal(                           # type: ignore[override]
        self,
        df_1min: pd.DataFrame,
        df_5min: pd.DataFrame,
        market_data: dict,
        options_data: dict,
    ) -> TradeSignal:
        """
        Generate a scalping signal from 1min + 5min data.

        Parameters
        ----------
        df_1min      : 1-minute OHLCV+RSI DataFrame.
        df_5min      : 5-minute OHLCV DataFrame (for S/R calculation).
        market_data  : live snapshot dict. Required: 'spot_price'.
        options_data : option chain dict keyed by integer strike.

        Returns
        -------
        TradeSignal with action BUY_CE | BUY_PE | NO_TRADE.
        """
        if not self.is_trading_hours():
            return _no_trade(self.name, "Outside trading hours")

        # Avoid entering scalps too close to EOD
        now_ist = datetime.now(IST)
        now_mins = now_ist.hour * 60 + now_ist.minute
        if now_mins >= 15 * 60:   # no new scalp entries after 15:00
            return _no_trade(self.name, "No new scalp entries after 15:00 IST")

        if not self._has_minimum_rows(df_1min, _MIN_ROWS_1MIN):
            return _no_trade(
                self.name, f"Need ≥{_MIN_ROWS_1MIN} 1min rows; got {len(df_1min)}"
            )
        if not self._has_minimum_rows(df_5min, _MIN_ROWS_5MIN):
            return _no_trade(
                self.name, f"Need ≥{_MIN_ROWS_5MIN} 5min rows; got {len(df_5min)}"
            )
        if not self._required_columns_present(df_1min, _REQUIRED_COLS_1MIN):
            return _no_trade(self.name, "1min DataFrame missing required columns")

        spot_price: float = float(market_data.get("spot_price", 0.0))
        if spot_price <= 0:
            return _no_trade(self.name, "Invalid spot price")

        # ---- Compute 5min S/R ----
        support, resistance = self._compute_sr(df_5min)
        if support is None or resistance is None:
            return _no_trade(self.name, "Could not compute S/R from 5min chart")

        logger.debug(
            f"[{self.name}] S/R — support={support:.2f}, resistance={resistance:.2f}, "
            f"spot={spot_price:.2f}"
        )

        # ---- Latest 1min bar ----
        latest   = df_1min.iloc[-1]
        close:   float = float(latest["close"])
        open_:   float = float(latest["open"])
        volume:  float = float(latest["volume"])
        rsi:     float = float(latest["rsi"])
        atr:     float = float(df_1min["high"].iloc[-1] - df_1min["low"].iloc[-1])

        # Average volume over last N bars (excluding current)
        avg_volume = float(
            df_1min["volume"].iloc[max(-_VOLUME_LOOKBACK - 1, -len(df_1min)):-1].mean()
        )
        if avg_volume <= 0:
            avg_volume = volume  # fallback to current

        vol_confirmed = volume >= _VOLUME_CONFIRMATION_MULTIPLIER * avg_volume

        # ---- Proximity checks ----
        near_support    = _is_near_level(close, support,    _SR_PROXIMITY_PCT)
        near_resistance = _is_near_level(close, resistance, _SR_PROXIMITY_PCT)

        bullish_candle = close > open_
        bearish_candle = close < open_

        # ---- BUY_CE: bounce from support ----
        if (
            near_support
            and bullish_candle
            and rsi > _RSI_BOUNCE_MIN
            and vol_confirmed
        ):
            reasons = [
                f"Price {close:.2f} near support {support:.2f} "
                f"(Δ={abs(close-support)/support*100:.2f}%)",
                f"Bullish 1min candle (O={open_:.2f} C={close:.2f})",
                f"RSI {rsi:.1f} > {_RSI_BOUNCE_MIN} (momentum intact)",
                f"Volume {volume:.0f} ≥ {_VOLUME_CONFIRMATION_MULTIPLIER}× avg ({avg_volume:.0f})",
            ]
            return self._build_signal(
                direction="CE",
                spot_price=spot_price,
                atr=atr,
                options_data=options_data,
                market_data=market_data,
                reasons=reasons,
            )

        # ---- BUY_PE: rejection from resistance ----
        if (
            near_resistance
            and bearish_candle
            and rsi < _RSI_BEAR_MAX
            and vol_confirmed
        ):
            reasons = [
                f"Price {close:.2f} near resistance {resistance:.2f} "
                f"(Δ={abs(close-resistance)/resistance*100:.2f}%)",
                f"Bearish 1min candle (O={open_:.2f} C={close:.2f})",
                f"RSI {rsi:.1f} < {_RSI_BEAR_MAX} (bearish momentum)",
                f"Volume {volume:.0f} ≥ {_VOLUME_CONFIRMATION_MULTIPLIER}× avg ({avg_volume:.0f})",
            ]
            return self._build_signal(
                direction="PE",
                spot_price=spot_price,
                atr=atr,
                options_data=options_data,
                market_data=market_data,
                reasons=reasons,
            )

        # ---- No signal ----
        diag_parts = []
        if not near_support and not near_resistance:
            diag_parts.append(
                f"price {close:.2f} not near S({support:.2f}) or R({resistance:.2f})"
            )
        if not vol_confirmed:
            diag_parts.append(
                f"volume {volume:.0f} < {_VOLUME_CONFIRMATION_MULTIPLIER}× avg ({avg_volume:.0f})"
            )
        if near_support and not bullish_candle:
            diag_parts.append("near support but candle not bullish")
        if near_resistance and not bearish_candle:
            diag_parts.append("near resistance but candle not bearish")

        return _no_trade(self.name, "; ".join(diag_parts) or "No scalp setup")

    # ------------------------------------------------------------------
    # Override: the scalping strategy has a 4-arg generate_signal.
    # Provide a 3-arg shim so base ABC contract is satisfied when called
    # generically.
    # ------------------------------------------------------------------

    def generate_signal(                           # noqa: F811  (intentional override)
        self,
        df,
        market_data,
        options_data,
        df_5min: Optional[pd.DataFrame] = None,
    ) -> TradeSignal:
        """
        Unified entry-point matching the BaseStrategy ABC signature.

        When called with only 3 positional args (df, market_data, options_data),
        df is treated as the 1min DataFrame and a 5min DataFrame must be
        embedded in market_data under the key 'df_5min'.

        When called with 4 args the 4th arg is df_5min directly.
        """
        if df_5min is None:
            df_5min = market_data.get("df_5min")
        if df_5min is None:
            return _no_trade(self.name, "No 5min DataFrame provided for S/R calculation")
        return self._generate_signal_impl(df, df_5min, market_data, options_data)

    def _generate_signal_impl(
        self,
        df_1min: pd.DataFrame,
        df_5min: pd.DataFrame,
        market_data: dict,
        options_data: dict,
    ) -> TradeSignal:
        """Actual signal generation — separated so tests can call directly."""
        if not self.is_trading_hours():
            return _no_trade(self.name, "Outside trading hours")

        now_ist  = datetime.now(IST)
        now_mins = now_ist.hour * 60 + now_ist.minute
        if now_mins >= 15 * 60:
            return _no_trade(self.name, "No new scalp entries after 15:00 IST")

        if not self._has_minimum_rows(df_1min, _MIN_ROWS_1MIN):
            return _no_trade(
                self.name, f"Need ≥{_MIN_ROWS_1MIN} 1min rows; got {len(df_1min)}"
            )
        if not self._has_minimum_rows(df_5min, _MIN_ROWS_5MIN):
            return _no_trade(
                self.name, f"Need ≥{_MIN_ROWS_5MIN} 5min rows; got {len(df_5min)}"
            )
        if not self._required_columns_present(df_1min, _REQUIRED_COLS_1MIN):
            return _no_trade(self.name, "1min DataFrame missing required columns")

        spot_price: float = float(market_data.get("spot_price", 0.0))
        if spot_price <= 0:
            return _no_trade(self.name, "Invalid spot price")

        support, resistance = self._compute_sr(df_5min)
        if support is None or resistance is None:
            return _no_trade(self.name, "Could not compute S/R from 5min chart")

        logger.debug(
            f"[{self.name}] S/R — support={support:.2f}, "
            f"resistance={resistance:.2f}, spot={spot_price:.2f}"
        )

        latest  = df_1min.iloc[-1]
        close:  float = float(latest["close"])
        open_:  float = float(latest["open"])
        volume: float = float(latest["volume"])
        rsi:    float = float(latest["rsi"])
        atr:    float = float(df_1min["high"].iloc[-1] - df_1min["low"].iloc[-1])
        atr             = max(atr, 1.0)

        vol_window  = df_1min["volume"].iloc[
            max(-_VOLUME_LOOKBACK - 1, -len(df_1min)):-1
        ]
        avg_volume  = float(vol_window.mean()) if len(vol_window) > 0 else volume
        if avg_volume <= 0:
            avg_volume = volume

        vol_confirmed   = volume >= _VOLUME_CONFIRMATION_MULTIPLIER * avg_volume
        near_support    = _is_near_level(close, support,    _SR_PROXIMITY_PCT)
        near_resistance = _is_near_level(close, resistance, _SR_PROXIMITY_PCT)
        bullish_candle  = close > open_
        bearish_candle  = close < open_

        # BUY_CE — bounce from support
        if near_support and bullish_candle and rsi > _RSI_BOUNCE_MIN and vol_confirmed:
            reasons = [
                f"Price {close:.2f} bouncing from support {support:.2f} "
                f"(Δ={abs(close-support)/max(support,1)*100:.2f}%)",
                f"Bullish 1min candle (O={open_:.2f} C={close:.2f})",
                f"RSI {rsi:.1f} > {_RSI_BOUNCE_MIN}",
                f"Volume {volume:.0f} ≥ {_VOLUME_CONFIRMATION_MULTIPLIER}× avg ({avg_volume:.0f})",
            ]
            return self._build_signal("CE", spot_price, atr, options_data, market_data, reasons)

        # BUY_PE — rejection from resistance
        if near_resistance and bearish_candle and rsi < _RSI_BEAR_MAX and vol_confirmed:
            reasons = [
                f"Price {close:.2f} rejected from resistance {resistance:.2f} "
                f"(Δ={abs(close-resistance)/max(resistance,1)*100:.2f}%)",
                f"Bearish 1min candle (O={open_:.2f} C={close:.2f})",
                f"RSI {rsi:.1f} < {_RSI_BEAR_MAX}",
                f"Volume {volume:.0f} ≥ {_VOLUME_CONFIRMATION_MULTIPLIER}× avg ({avg_volume:.0f})",
            ]
            return self._build_signal("PE", spot_price, atr, options_data, market_data, reasons)

        diag_parts = []
        if not (near_support or near_resistance):
            diag_parts.append(
                f"price {close:.2f} not near S({support:.2f}) or R({resistance:.2f})"
            )
        if not vol_confirmed:
            diag_parts.append(
                f"vol {volume:.0f} < {_VOLUME_CONFIRMATION_MULTIPLIER}×avg({avg_volume:.0f})"
            )
        return _no_trade(self.name, "; ".join(diag_parts) or "No scalp setup")

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    def should_exit(
        self,
        position: dict,
        current_data: dict,
    ) -> tuple[bool, str]:
        """
        Fast scalp exit logic.

        Priority:
        1. Time-based: 15:20 IST hard cut-off.
        2. Max hold: 15 minutes.
        3. SL hit on option premium.
        4. Target hit on option premium (fixed point gain).
        """
        ltp:          float    = float(current_data.get("ltp", 0.0))
        sl_price:     float    = float(position.get("sl_price", 0.0))
        target_price: float    = float(position.get("target_price", 0.0))
        entry_time:   datetime = position.get("entry_time", datetime.now(IST))
        symbol:       str      = position.get("symbol", "")
        now_ist = datetime.now(IST)

        # ---- 1. Hard EOD cut-off ----
        now_mins = now_ist.hour * 60 + now_ist.minute
        if now_mins >= 15 * 60 + 20:
            return True, f"EOD square-off at {now_ist.strftime('%H:%M')} IST"

        # ---- 2. Max hold time ----
        if isinstance(entry_time, datetime):
            if entry_time.tzinfo is None:
                entry_time = IST.localize(entry_time)
            held_minutes = (now_ist - entry_time).total_seconds() / 60.0
            if held_minutes > self.max_hold_minutes:
                return True, (
                    f"Scalp max hold exceeded ({held_minutes:.0f} min > "
                    f"{self.max_hold_minutes} min)"
                )

        # ---- 3. SL hit ----
        if sl_price > 0 and ltp <= sl_price:
            logger.warning(
                f"[{self.name}] Scalp SL hit {symbol}: LTP={ltp:.2f} ≤ SL={sl_price:.2f}"
            )
            return True, f"Scalp SL hit (LTP={ltp:.2f} ≤ SL={sl_price:.2f})"

        # ---- 4. Target hit ----
        if target_price > 0 and ltp >= target_price:
            logger.info(
                f"[{self.name}] Scalp target hit {symbol}: "
                f"LTP={ltp:.2f} ≥ target={target_price:.2f}"
            )
            return True, f"Scalp target hit (LTP={ltp:.2f} ≥ target={target_price:.2f})"

        return False, ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_sr(
        self, df_5min: pd.DataFrame
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Derive intraday support and resistance from the 5-minute chart.

        Uses rolling min/max over the configured lookback window (excluding
        the last bar to avoid look-ahead bias).

        Returns
        -------
        (support_level, resistance_level) or (None, None) on failure.
        """
        if len(df_5min) < self.sr_lookback:
            logger.warning(
                f"[{self.name}] 5min DataFrame too short for SR "
                f"({len(df_5min)} < {self.sr_lookback})"
            )
            return None, None

        if "low" not in df_5min.columns or "high" not in df_5min.columns:
            logger.warning(f"[{self.name}] 5min DataFrame missing high/low columns")
            return None, None

        # Exclude the current (last) bar to avoid look-ahead
        lookback_window = df_5min.iloc[-self.sr_lookback - 1:-1]
        if len(lookback_window) == 0:
            return None, None

        support    = float(lookback_window["low"].min())
        resistance = float(lookback_window["high"].max())

        # Sanity check: S/R must be a meaningful distance apart
        if resistance <= support:
            logger.warning(
                f"[{self.name}] S/R inversion detected "
                f"(S={support:.2f} R={resistance:.2f})"
            )
            return None, None

        return support, resistance

    def _build_signal(
        self,
        direction: str,
        spot_price: float,
        atr: float,
        options_data: dict,
        market_data: dict,
        reasons: list[str],
    ) -> TradeSignal:
        """Construct a complete scalp TradeSignal."""
        option_type = direction
        action      = f"BUY_{option_type}"

        strike = self._get_atm_strike(spot_price)

        strike_data = options_data.get(strike, {})
        opt_data    = strike_data.get(option_type, {})
        premium:  float = float(opt_data.get("ltp", 0.0))
        symbol:   str   = opt_data.get("symbol",  f"NIFTY{strike}{option_type}")
        token:    str   = opt_data.get("token",   "0")
        expiry:   str   = opt_data.get("expiry",  market_data.get("nearest_expiry", ""))

        if premium <= 0:
            premium = max(atr * 10.0, 5.0)
            logger.warning(
                f"[{self.name}] No live premium for {symbol}; estimating ≈ {premium:.2f}"
            )

        # Fixed-point target for scalps; SL is pct-based
        sl_price     = round(premium * (1.0 - self.sl_pct), 2)
        target_price = round(premium + self.target_points, 2)

        lot_size = self.get_lot_size()
        lots     = int(self.trading_cfg.get("max_lots_per_trade", 1))
        qty      = lots * lot_size

        signal = TradeSignal(
            action           = action,
            symbol           = symbol,
            token            = token,
            exchange         = "NFO",
            qty              = qty,
            transaction_type = "BUY",
            order_type       = "MARKET",
            price            = 0.0,
            strike           = strike,
            option_type      = option_type,
            expiry           = expiry,
            confidence       = 0.75,    # scalp signals are moderate confidence
            strategy_name    = self.name,
            reasons          = reasons,
            sl_price         = sl_price,
            target_price     = target_price,
        )
        self._log_signal(signal)
        return signal


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _is_near_level(price: float, level: float, tolerance_pct: float) -> bool:
    """Return True if price is within tolerance_pct % of level."""
    if level <= 0:
        return False
    return abs(price - level) / level * 100.0 <= tolerance_pct
