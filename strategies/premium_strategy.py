"""
Options Premium Selling Strategy for Nifty50 Intraday.

⚠️ DEAD CODE — THIS FILE IS NOT REACHABLE ⚠️
═════════════════════════════════════════════

This strategy cannot execute. OrderManager.execute_signal() has a hard block at
line 149-163 that rejects all SELL_STRADDLE / SELL_STRANGLE signals:

    if signal.action in ("SELL_STRADDLE", "SELL_STRANGLE"):
        logger.warning("[OrderManager] Trade blocked — option selling is strictly disabled.")
        return None

The block exists because naked option selling carries undefined losses. The entire
14.5 KB strategy file is unreachable dead code that generates trading signals rejected
before any execution logic runs.

WHAT THIS MEANS:
• All signal generation is wasted CPU
• Any changes to this file will have ZERO effect on the system
• If the block is ever removed, leg-2 placement has no atomic protection
  (see order_manager.py:284-312 for the gap)

RECOMMENDATION:
Delete this file. If you need covered options strategies, use weekly_income_trader.py,
which uses defined-risk call spreads with proper Greeks calculation.

────────────────────────────────────────────────────────────────────────────────

Original docstring below (for historical reference):

Sells short straddles (ATM CE + ATM PE) or short strangles (OTM1 CE + OTM1 PE)
when the market is in a ranging regime, implied volatility is elevated, and the
Put-Call Ratio is near equilibrium.

Exit when premium has decayed by the profit target or a stop-loss on the
net credit received is triggered.
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

_REQUIRED_COLS = ["close", "adx", "atr"]
_MIN_ROWS = 20


class PremiumSellingStrategy(BaseStrategy):
    """
    Short straddle / strangle strategy.

    Entry (all must hold):
        • ADX < adx_ranging_max (20) — market is ranging, not trending
        • IV percentile > min_iv_percentile (60th)  — elevated IV, good premium
        • IV percentile < max_iv_percentile (90th)  — not dangerously high (event risk)
        • PCR between pcr_lo (0.8) and pcr_hi (1.2) — balanced market

    Instrument selection:
        • IV percentile in [min_iv_pct, 70) → SELL_STRADDLE  (ATM CE + ATM PE)
        • IV percentile ≥ 70               → SELL_STRANGLE (OTM1 CE + OTM1 PE)

    Exit:
        • Net premium received has decayed by profit_decay_pct (50 %) → take profit
        • Net premium has expanded by sl_expansion_pct (50 %) → cut loss
        • Time-based square-off at 15:20 IST
    """

    def __init__(self, config: dict) -> None:
        super().__init__(config, name="PremiumSelling")

        strat_cfg = self.strategy_cfg.get("premium_selling", {})
        risk_cfg  = self.risk_cfg

        self.adx_ranging_max:    float = 20.0
        self.min_iv_percentile:  float = float(strat_cfg.get("min_iv_percentile", 60))
        self.max_iv_percentile:  float = float(strat_cfg.get("max_iv_percentile", 90))
        self.strangle_iv_thresh: float = 70.0   # use strangle above this IV percentile
        self.pcr_lo:             float = 0.8
        self.pcr_hi:             float = 1.2

        # Exit thresholds relative to net premium received
        self.profit_decay_pct:   float = 0.50   # exit when 50 % of credit captured
        self.sl_expansion_pct:   float = float(risk_cfg.get("option_sell_sl_pct", 0.50))

        # Strangle width in OTM levels
        self.strangle_width: int = 1            # 1 level OTM on each side

        logger.info(
            f"[{self.name}] Config — ADX<{self.adx_ranging_max}, "
            f"IV_pct=[{self.min_iv_percentile}-{self.max_iv_percentile}], "
            f"PCR=[{self.pcr_lo}-{self.pcr_hi}], "
            f"profit_decay={self.profit_decay_pct*100:.0f}%, "
            f"SL_expansion={self.sl_expansion_pct*100:.0f}%"
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
        Evaluate market conditions and emit a premium-selling signal.

        Parameters
        ----------
        df           : OHLCV+indicator DataFrame.  Must contain at minimum
                       'close', 'adx', 'atr'.
        market_data  : live snapshot dict.
                       Required: 'spot_price'
                       Optional: 'iv_percentile', 'pcr', 'nearest_expiry'
        options_data : option chain dict keyed by integer strike.
                       {18400: {'CE': {'ltp': 85.0, 'token': '35227', ...},
                                'PE': {'ltp': 55.0, 'token': '35229', ...}}}

        Returns
        -------
        TradeSignal with action SELL_STRADDLE | SELL_STRANGLE | NO_TRADE.
        For multi-leg trades the signal represents the combined position;
        the OrderManager is responsible for splitting into two individual legs.
        """
        if not self.is_trading_hours():
            return _no_trade(self.name, "Outside trading hours")

        if not self._has_minimum_rows(df, _MIN_ROWS):
            return _no_trade(self.name, f"Need ≥{_MIN_ROWS} rows; got {len(df)}")

        if not self._required_columns_present(df, _REQUIRED_COLS):
            return _no_trade(self.name, "Missing required indicator columns")

        spot_price:    float = float(market_data.get("spot_price", 0.0))
        iv_percentile: float = float(market_data.get("iv_percentile", 0.0))
        pcr:           float = float(market_data.get("pcr", 1.0))

        if spot_price <= 0:
            return _no_trade(self.name, "Invalid spot price in market_data")

        latest = df.iloc[-1]
        adx:    float = float(latest["adx"])
        atr:    float = float(latest["atr"])

        logger.debug(
            f"[{self.name}] ADX={adx:.1f}, IV_pct={iv_percentile:.1f}, PCR={pcr:.2f}"
        )

        # ---- Gate 1: Market must be ranging ----
        if adx >= self.adx_ranging_max:
            return _no_trade(
                self.name,
                f"ADX {adx:.1f} ≥ {self.adx_ranging_max} (trending — premium selling risky)"
            )

        # ---- Gate 2: IV must be in the sweet spot ----
        if iv_percentile < self.min_iv_percentile:
            return _no_trade(
                self.name,
                f"IV percentile {iv_percentile:.1f} < {self.min_iv_percentile} (premium too low)"
            )
        if iv_percentile > self.max_iv_percentile:
            return _no_trade(
                self.name,
                f"IV percentile {iv_percentile:.1f} > {self.max_iv_percentile} (event risk — skip)"
            )

        # ---- Gate 3: PCR must be near equilibrium ----
        if not (self.pcr_lo <= pcr <= self.pcr_hi):
            return _no_trade(
                self.name,
                f"PCR {pcr:.2f} outside equilibrium band [{self.pcr_lo}-{self.pcr_hi}]"
            )

        # ---- All gates passed — choose straddle vs strangle ----
        reasons = [
            f"ADX {adx:.1f} < {self.adx_ranging_max} (ranging)",
            f"IV percentile {iv_percentile:.1f} in [{self.min_iv_percentile}-{self.max_iv_percentile}]",
            f"PCR {pcr:.2f} near equilibrium [{self.pcr_lo}-{self.pcr_hi}]",
        ]

        use_strangle = iv_percentile >= self.strangle_iv_thresh

        if use_strangle:
            action     = "SELL_STRANGLE"
            otm_levels = self.strangle_width
            ce_strike  = self._get_otm_strike(spot_price, "CE", levels=otm_levels)
            pe_strike  = self._get_otm_strike(spot_price, "PE", levels=otm_levels)
            reasons.append(
                f"IV_pct {iv_percentile:.1f} ≥ {self.strangle_iv_thresh} → OTM{otm_levels} strangle"
            )
        else:
            action    = "SELL_STRADDLE"
            atm       = self._get_atm_strike(spot_price)
            ce_strike = atm
            pe_strike = atm
            reasons.append(f"IV_pct {iv_percentile:.1f} < {self.strangle_iv_thresh} → ATM straddle")

        # ---- Fetch CE leg data ----
        ce_data    = options_data.get(ce_strike, {}).get("CE", {})
        ce_premium = float(ce_data.get("ltp", 0.0))
        ce_symbol  = ce_data.get("symbol",  f"NIFTY{ce_strike}CE")
        ce_token   = ce_data.get("token",   "0")
        expiry     = ce_data.get("expiry",  market_data.get("nearest_expiry", ""))

        # ---- Fetch PE leg data ----
        pe_data    = options_data.get(pe_strike, {}).get("PE", {})
        pe_premium = float(pe_data.get("ltp", 0.0))
        pe_symbol  = pe_data.get("symbol",  f"NIFTY{pe_strike}PE")
        pe_token   = pe_data.get("token",   "0")

        # Estimate premiums from ATR if live data unavailable
        if ce_premium <= 0:
            ce_premium = max(atr * 12.0, 8.0)
            logger.warning(
                f"[{self.name}] No live CE premium for {ce_symbol}; "
                f"estimating ≈ {ce_premium:.2f}"
            )
        if pe_premium <= 0:
            pe_premium = max(atr * 12.0, 8.0)
            logger.warning(
                f"[{self.name}] No live PE premium for {pe_symbol}; "
                f"estimating ≈ {pe_premium:.2f}"
            )

        net_premium = ce_premium + pe_premium
        reasons.append(
            f"CE={ce_symbol}@{ce_premium:.2f}, PE={pe_symbol}@{pe_premium:.2f}, "
            f"net_credit={net_premium:.2f}"
        )

        # ---- SL and target on net premium received ----
        # Take profit: net_premium falls to (1 - profit_decay_pct) * net_premium
        # i.e., we've captured profit_decay_pct fraction of the credit
        target_price = round(net_premium * (1.0 - self.profit_decay_pct), 2)
        # Stop loss: net_premium expands by sl_expansion_pct (position goes against us)
        sl_price     = round(net_premium * (1.0 + self.sl_expansion_pct), 2)

        lot_size  = self.get_lot_size()
        lots      = int(self.trading_cfg.get("max_lots_per_trade", 1))
        qty       = lots * lot_size

        # Confidence: proportional to how deep we are into IV percentile sweet-spot
        iv_range  = self.max_iv_percentile - self.min_iv_percentile
        iv_depth  = (iv_percentile - self.min_iv_percentile) / max(iv_range, 1.0)
        confidence = min(0.5 + iv_depth * 0.5, 1.0)

        # The signal represents the combined straddle/strangle.
        # We encode CE leg in the primary fields; PE leg details go in reasons.
        # OrderManager splits this into two SELL orders.
        signal = TradeSignal(
            action           = action,
            symbol           = ce_symbol,    # CE leg as primary
            token            = ce_token,
            exchange         = "NFO",
            qty              = qty,
            transaction_type = "SELL",
            order_type       = "MARKET",
            price            = 0.0,
            strike           = ce_strike,
            option_type      = "CE",
            expiry           = expiry,
            confidence       = round(confidence, 3),
            strategy_name    = self.name,
            reasons          = reasons,
            sl_price         = sl_price,
            target_price     = target_price,
        )
        # Attach PE leg metadata so OrderManager can place both legs
        signal.__dict__["pe_symbol"]  = pe_symbol
        signal.__dict__["pe_token"]   = pe_token
        signal.__dict__["pe_strike"]  = pe_strike
        signal.__dict__["pe_premium"] = pe_premium
        signal.__dict__["ce_premium"] = ce_premium
        signal.__dict__["net_credit"] = net_premium

        self._log_signal(signal)
        return signal

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    def should_exit(
        self,
        position: dict,
        current_data: dict,
    ) -> tuple[bool, str]:
        """
        Decide whether to exit a short straddle/strangle position.

        For SELL positions the P&L is opposite to premium direction:
            • If current combined premium < target_price → take profit
            • If current combined premium > sl_price     → cut loss

        Parameters
        ----------
        position     : PositionManager entry dict.
                       Extra keys expected for multi-leg:
                           'ce_current_ltp', 'pe_current_ltp',
                           'net_credit_received'
        current_data : live snapshot dict.
                       Keys: 'ltp' (CE leg), 'pe_ltp' (PE leg), 'timestamp'
        """
        # ---- Reconstruct net current premium ----
        ce_ltp: float = float(current_data.get("ltp", 0.0))
        pe_ltp: float = float(current_data.get("pe_ltp", ce_ltp))  # fallback to CE ltp
        net_current  = ce_ltp + pe_ltp

        target_price:   float = float(position.get("target_price",  0.0))
        sl_price:       float = float(position.get("sl_price",      0.0))
        entry_time:     datetime = position.get("entry_time", datetime.now(IST))
        symbol:         str   = position.get("symbol", "")
        net_credit:     float = float(position.get("net_credit", net_current))

        now_ist = datetime.now(IST)

        # ---- 1. Time-based square-off ----
        now_mins = now_ist.hour * 60 + now_ist.minute
        if now_mins >= 15 * 60 + 20:
            return True, f"Time-based square-off at {now_ist.strftime('%H:%M')} IST"

        # ---- 2. Profit target: premium has decayed enough ----
        if target_price > 0 and net_current <= target_price:
            profit_pct = (net_credit - net_current) / max(net_credit, 0.01) * 100.0
            logger.info(
                f"[{self.name}] Profit target hit on {symbol}: "
                f"net_premium={net_current:.2f} ≤ target={target_price:.2f} "
                f"(captured {profit_pct:.1f}%)"
            )
            return True, (
                f"Profit target hit: net_premium={net_current:.2f} ≤ {target_price:.2f} "
                f"({profit_pct:.1f}% credit captured)"
            )

        # ---- 3. Stop-loss: premium has expanded against us ----
        if sl_price > 0 and net_current >= sl_price:
            loss_pct = (net_current - net_credit) / max(net_credit, 0.01) * 100.0
            logger.warning(
                f"[{self.name}] SL hit on {symbol}: "
                f"net_premium={net_current:.2f} ≥ SL={sl_price:.2f} "
                f"(loss {loss_pct:.1f}%)"
            )
            return True, (
                f"Stop-loss hit: net_premium={net_current:.2f} ≥ {sl_price:.2f} "
                f"(loss {loss_pct:.1f}%)"
            )

        # ---- 4. Max holding time for premium selling (90 min) ----
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
