"""
Trend Following Strategy for Nifty50 Intraday Options.

Buys CE on confirmed uptrend and PE on confirmed downtrend using a
multi-indicator confluence approach:  EMA crossover, RSI zone, MACD
histogram polarity, VWAP position, SuperTrend direction, and ADX
trend-strength filter.

Stop-loss is ATR-based; target is set at a 2:1 reward-to-risk ratio.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
import pytz
from loguru import logger

from strategies.base_strategy import BaseStrategy, TradeSignal, _no_trade

IST = pytz.timezone("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REQUIRED_COLS = [
    "close", "high", "low",
    "ema_9", "ema_21",
    "rsi",
    "macd_hist",
    "vwap",
    "atr",
    "adx",
    "supertrend_dir",
]

_MIN_ROWS = 30


class TrendFollowingStrategy(BaseStrategy):
    """
    Trend-following options strategy.

    Entry conditions (all must hold simultaneously):
        UPTREND  → BUY_CE
            • EMA9  > EMA21
            • RSI between rsi_bull_lo (50) and rsi_bull_hi (70)
            • MACD histogram > 0
            • Close > VWAP
            • SuperTrend direction == +1  (bullish)
            • ADX > adx_threshold (20) — trend is strong

        DOWNTREND → BUY_PE
            • EMA9  < EMA21
            • RSI between rsi_bear_lo (30) and rsi_bear_hi (50)
            • MACD histogram < 0
            • Close < VWAP
            • SuperTrend direction == -1  (bearish)
            • ADX > adx_threshold (20) — trend is strong

    SL / Target:
        sl_price     = premium × (1 - option_buy_sl_pct)
        target_price = premium × (1 + option_buy_target_pct)
        If premium is unknown (0), sl/target are estimated from ATR:
            estimated_premium ≈ ATR * 15  (rough options pricing proxy)
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config, name="TrendFollowing")

        strat_cfg = self.strategy_cfg.get("trend_following", {})
        ind_cfg   = strat_cfg.get("entry_indicators", {})

        # RSI thresholds
        self.rsi_bull_lo: float = float(ind_cfg.get("rsi_oversold",   50))
        self.rsi_bull_hi: float = float(ind_cfg.get("rsi_overbought", 70))
        self.rsi_bear_lo: float = 100.0 - self.rsi_bull_hi   # 30
        self.rsi_bear_hi: float = 100.0 - self.rsi_bull_lo   # 50

        # ADX threshold
        self.adx_threshold: float = 20.0

        # Risk params
        risk_cfg = self.risk_cfg
        self.sl_pct:     float = float(risk_cfg.get("option_buy_sl_pct",     0.30))
        self.target_pct: float = float(risk_cfg.get("option_buy_target_pct", 0.60))

        # Strike selection
        self.strike_selection: str = strat_cfg.get("strike_selection", "ATM")

        logger.info(
            f"[{self.name}] Config loaded — "
            f"RSI bull={self.rsi_bull_lo}-{self.rsi_bull_hi}, "
            f"RSI bear={self.rsi_bear_lo}-{self.rsi_bear_hi}, "
            f"ADX>{self.adx_threshold}, "
            f"SL={self.sl_pct*100:.0f}%, Target={self.target_pct*100:.0f}%"
        )

    # ------------------------------------------------------------------
    # Primary signal generation
    # ------------------------------------------------------------------

    def generate_signal(
        self,
        df: pd.DataFrame,
        market_data: dict,
        options_data: dict,
    ) -> TradeSignal:
        """
        Analyse the current OHLCV+indicator DataFrame and emit a signal.

        Parameters
        ----------
        df           : DataFrame with at minimum the columns listed in
                       _REQUIRED_COLS (produced by TechnicalFeatureEngine).
        market_data  : live snapshot dict.
                       Required keys: 'spot_price'
                       Optional keys: 'nearest_expiry', 'pcr'
        options_data : option chain dict keyed by strike.
                       e.g. {18400: {'CE': {'ltp': 85.0, 'token': '35227', ...},
                                     'PE': {'ltp': 55.0, 'token': '35229', ...}}}

        Returns
        -------
        TradeSignal
        """
        if not self.is_trading_hours():
            return _no_trade(self.name, "Outside trading hours")

        if not self._has_minimum_rows(df, _MIN_ROWS):
            return _no_trade(self.name, f"Need ≥{_MIN_ROWS} rows; got {len(df)}")

        if not self._required_columns_present(df, _REQUIRED_COLS):
            return _no_trade(self.name, "Missing required indicator columns")

        spot_price: float = float(market_data.get("spot_price", 0.0))
        if spot_price <= 0:
            return _no_trade(self.name, "Invalid spot price in market_data")

        # ---- Read latest bar values ----
        latest = df.iloc[-1]
        ema9:          float = float(latest["ema_9"])
        ema21:         float = float(latest["ema_21"])
        rsi:           float = float(latest["rsi"])
        macd_hist:     float = float(latest["macd_hist"])
        vwap:          float = float(latest["vwap"])
        close:         float = float(latest["close"])
        atr:           float = float(latest["atr"])
        adx:           float = float(latest["adx"])
        st_dir:        float = float(latest["supertrend_dir"])   # +1 or -1

        logger.debug(
            f"[{self.name}] Indicators — EMA9={ema9:.2f} EMA21={ema21:.2f} "
            f"RSI={rsi:.1f} MACD_hist={macd_hist:.4f} VWAP={vwap:.2f} "
            f"ADX={adx:.1f} ST_dir={st_dir}"
        )

        # ---- ADX gate — trend must be strong enough ----
        if adx < self.adx_threshold:
            return _no_trade(
                self.name,
                f"ADX {adx:.1f} < threshold {self.adx_threshold} (ranging market)"
            )

        # ---- Check uptrend conditions ----
        uptrend_reasons: list[str] = []
        uptrend_checks: list[bool] = []

        ema_bull = ema9 > ema21
        uptrend_checks.append(ema_bull)
        if ema_bull:
            uptrend_reasons.append(f"EMA9({ema9:.1f}) > EMA21({ema21:.1f})")

        rsi_bull = self.rsi_bull_lo <= rsi <= self.rsi_bull_hi
        uptrend_checks.append(rsi_bull)
        if rsi_bull:
            uptrend_reasons.append(
                f"RSI {rsi:.1f} in bull zone [{self.rsi_bull_lo}-{self.rsi_bull_hi}]"
            )

        macd_bull = macd_hist > 0
        uptrend_checks.append(macd_bull)
        if macd_bull:
            uptrend_reasons.append(f"MACD hist {macd_hist:.4f} > 0")

        price_above_vwap = close > vwap
        uptrend_checks.append(price_above_vwap)
        if price_above_vwap:
            uptrend_reasons.append(f"Close({close:.1f}) > VWAP({vwap:.1f})")

        st_bull = st_dir == 1
        uptrend_checks.append(st_bull)
        if st_bull:
            uptrend_reasons.append("SuperTrend bullish")

        uptrend_reasons.append(f"ADX {adx:.1f} > {self.adx_threshold} (strong trend)")

        # ---- Check downtrend conditions ----
        downtrend_reasons: list[str] = []
        downtrend_checks: list[bool] = []

        ema_bear = ema9 < ema21
        downtrend_checks.append(ema_bear)
        if ema_bear:
            downtrend_reasons.append(f"EMA9({ema9:.1f}) < EMA21({ema21:.1f})")

        rsi_bear = self.rsi_bear_lo <= rsi <= self.rsi_bear_hi
        downtrend_checks.append(rsi_bear)
        if rsi_bear:
            downtrend_reasons.append(
                f"RSI {rsi:.1f} in bear zone [{self.rsi_bear_lo}-{self.rsi_bear_hi}]"
            )

        macd_bear = macd_hist < 0
        downtrend_checks.append(macd_bear)
        if macd_bear:
            downtrend_reasons.append(f"MACD hist {macd_hist:.4f} < 0")

        price_below_vwap = close < vwap
        downtrend_checks.append(price_below_vwap)
        if price_below_vwap:
            downtrend_reasons.append(f"Close({close:.1f}) < VWAP({vwap:.1f})")

        st_bear = st_dir == -1
        downtrend_checks.append(st_bear)
        if st_bear:
            downtrend_reasons.append("SuperTrend bearish")

        downtrend_reasons.append(f"ADX {adx:.1f} > {self.adx_threshold} (strong trend)")

        # ---- Decide direction ----
        all_uptrend   = all(uptrend_checks)
        all_downtrend = all(downtrend_checks)

        if all_uptrend:
            return self._build_signal(
                direction="CE",
                spot_price=spot_price,
                atr=atr,
                options_data=options_data,
                market_data=market_data,
                reasons=uptrend_reasons,
            )

        if all_downtrend:
            return self._build_signal(
                direction="PE",
                spot_price=spot_price,
                atr=atr,
                options_data=options_data,
                market_data=market_data,
                reasons=downtrend_reasons,
            )

        # Build a diagnostic reason for NO_TRADE
        missing_up   = sum(1 for c in uptrend_checks   if not c)
        missing_down = sum(1 for c in downtrend_checks if not c)
        closer = "uptrend" if missing_up <= missing_down else "downtrend"
        return _no_trade(
            self.name,
            f"No clear trend: {missing_up} uptrend / {missing_down} downtrend "
            f"conditions failed (closer to {closer})"
        )

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    def should_exit(
        self,
        position: dict,
        current_data: dict,
    ) -> tuple[bool, str]:
        """
        Evaluate whether an open position should be exited.

        Checks (in order of priority):
        1. Stop-loss hit on option premium.
        2. Target hit on option premium.
        3. EMA crossover reversal (trend invalidation).
        4. Time-based exit (position held > max_holding_minutes or close to EOD).
        5. SuperTrend direction flip.

        Parameters
        ----------
        position     : dict from PositionManager book.
        current_data : dict with keys 'ltp', 'spot_price', 'timestamp', 'df'.

        Returns
        -------
        (bool, str)  — (exit_now, reason)
        """
        ltp:         float    = float(current_data.get("ltp", 0.0))
        sl_price:    float    = float(position.get("sl_price", 0.0))
        target_price: float   = float(position.get("target_price", 0.0))
        direction:   str      = position.get("direction", "CE")
        entry_time:  datetime = position.get("entry_time", datetime.now(IST))
        symbol:      str      = position.get("symbol", "")

        now_ist = datetime.now(IST)

        # ---- 1. SL hit ----
        if sl_price > 0 and ltp <= sl_price:
            logger.warning(
                f"[{self.name}] SL hit on {symbol}: "
                f"LTP={ltp:.2f} ≤ SL={sl_price:.2f}"
            )
            return True, f"Stop-loss hit (LTP={ltp:.2f} ≤ SL={sl_price:.2f})"

        # ---- 2. Target hit ----
        if target_price > 0 and ltp >= target_price:
            logger.info(
                f"[{self.name}] Target hit on {symbol}: "
                f"LTP={ltp:.2f} ≥ Target={target_price:.2f}"
            )
            return True, f"Target hit (LTP={ltp:.2f} ≥ Target={target_price:.2f})"

        # ---- 3. EMA crossover reversal (trend invalidation) ----
        df: Optional[pd.DataFrame] = current_data.get("df")
        if df is not None and len(df) >= 2:
            if "ema_9" in df.columns and "ema_21" in df.columns:
                latest_ema9  = float(df["ema_9"].iloc[-1])
                latest_ema21 = float(df["ema_21"].iloc[-1])
                if direction == "CE" and latest_ema9 < latest_ema21:
                    logger.info(
                        f"[{self.name}] EMA reversal for CE position {symbol}: "
                        f"EMA9({latest_ema9:.2f}) < EMA21({latest_ema21:.2f})"
                    )
                    return True, (
                        f"EMA reversal — trend reversed bearish "
                        f"(EMA9={latest_ema9:.2f} < EMA21={latest_ema21:.2f})"
                    )
                if direction == "PE" and latest_ema9 > latest_ema21:
                    logger.info(
                        f"[{self.name}] EMA reversal for PE position {symbol}: "
                        f"EMA9({latest_ema9:.2f}) > EMA21({latest_ema21:.2f})"
                    )
                    return True, (
                        f"EMA reversal — trend reversed bullish "
                        f"(EMA9={latest_ema9:.2f} > EMA21={latest_ema21:.2f})"
                    )

            # ---- 5. SuperTrend direction flip ----
            if "supertrend_dir" in df.columns:
                st_dir = float(df["supertrend_dir"].iloc[-1])
                if direction == "CE" and st_dir == -1:
                    return True, "SuperTrend flipped bearish — exit CE position"
                if direction == "PE" and st_dir == 1:
                    return True, "SuperTrend flipped bullish — exit PE position"

        # ---- 4. Time-based exit ----
        # No-new-trades cutoff from config; hard square-off at 15:20
        no_new_after_h, no_new_after_m = 15, 0
        square_off_h,   square_off_m   = 15, 20
        now_mins = now_ist.hour * 60 + now_ist.minute
        if now_mins >= square_off_h * 60 + square_off_m:
            return True, f"Time-based square-off at {now_ist.strftime('%H:%M')} IST"

        # Max holding: 90 minutes for trend trades
        max_holding_minutes = 90
        if isinstance(entry_time, datetime):
            if entry_time.tzinfo is None:
                entry_time = IST.localize(entry_time)
            held_minutes = (now_ist - entry_time).total_seconds() / 60.0
            if held_minutes > max_holding_minutes:
                return True, (
                    f"Max holding time exceeded ({held_minutes:.0f} min > "
                    f"{max_holding_minutes} min)"
                )

        return False, ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_signal(
        self,
        direction: str,
        spot_price: float,
        atr: float,
        options_data: dict,
        market_data: dict,
        reasons: list[str],
    ) -> TradeSignal:
        """Construct a complete TradeSignal for a directional options buy."""
        option_type = direction  # "CE" or "PE"
        action      = f"BUY_{option_type}"
        tx_type     = "BUY"

        # Strike selection
        if self.strike_selection == "OTM1":
            strike = self._get_otm_strike(spot_price, option_type, levels=1)
        elif self.strike_selection == "OTM2":
            strike = self._get_otm_strike(spot_price, option_type, levels=2)
        else:
            strike = self._get_atm_strike(spot_price)

        # Look up live option data for the chosen strike
        strike_data  = options_data.get(strike, {})
        opt_data     = strike_data.get(option_type, {})
        premium:  float = float(opt_data.get("ltp", 0.0))
        symbol:   str   = opt_data.get("symbol",   f"NIFTY{strike}{option_type}")
        token:    str   = opt_data.get("token",    "0")
        expiry:   str   = opt_data.get("expiry",   market_data.get("nearest_expiry", ""))

        # If live premium unavailable, estimate from ATR
        if premium <= 0:
            premium = max(atr * 15.0, 10.0)
            logger.warning(
                f"[{self.name}] No live premium for {symbol}; "
                f"estimating ≈ {premium:.2f} from ATR"
            )

        # SL and target on the option premium
        sl_price     = round(premium * (1.0 - self.sl_pct),     2)
        target_price = round(premium * (1.0 + self.target_pct), 2)

        lot_size = self.get_lot_size()
        lots     = int(self.trading_cfg.get("max_lots_per_trade", 1))
        qty      = lots * lot_size

        # Confidence: 1.0 because all 5 conditions + ADX gate passed
        confidence = 1.0

        signal = TradeSignal(
            action           = action,
            symbol           = symbol,
            token            = token,
            exchange         = "NFO",
            qty              = qty,
            transaction_type = tx_type,
            order_type       = "MARKET",
            price            = 0.0,
            strike           = strike,
            option_type      = option_type,
            expiry           = expiry,
            confidence       = confidence,
            strategy_name    = self.name,
            reasons          = reasons,
            sl_price         = sl_price,
            target_price     = target_price,
        )
        self._log_signal(signal)
        return signal
