"""
NIFTY Options Auto-Trader

Trades NIFTY options (calls/puts) using the same ML direction signal as NiftyMLTrader.
Paper trading for first few days → then switch to autopilot (live) once convinced.

Strategy:
- Entry: Use NiftyMLTrader's NIFTY direction prediction
- Strike: Select based on conviction level
- Greeks: Monitor Delta, Gamma, Theta, Vega for early exit
- Exit: Hit profit target (50-100%), stop loss (30%), or time decay (last 3 days to expiry)
- Risk: Max 2% portfolio per trade
- Position: One at a time
"""

import json
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, List, Tuple

import numpy as np
import pandas as pd
from loguru import logger
from scipy.stats import norm

from backend.ml.nifty_model import (
    MODEL_PATH, META_PATH, NIFTY_FEATURES, TARGET_PCT, SL_PCT,
    HOLD_CANDLES, ENTRY_CUTOFF_MIN, _ema, _rsi, _atr_pct,
)

_IST = timezone(timedelta(hours=5, minutes=30))

REPO_MODEL = Path(__file__).parent / "storage" / "nifty_xgb.json"
REPO_META = Path(__file__).parent / "storage" / "nifty_meta.json"

NIFTY_TOKEN = "26000"
NIFTY_OPTIONS_PREFIX = "NIFTY"  # NSE uses NIFTY24AUG15500CE format

# Expected volatility levels (will calibrate from market)
NIFTY_IMPLIED_VOL = 0.18  # ~18% IV (typical)
RISK_FREE_RATE = 0.065   # ~6.5% annual


class NiftyOptionsTrader:
    """Singleton: NIFTY ML → Options execution with Greeks management."""

    _instance = None

    @classmethod
    def get_instance(cls) -> "NiftyOptionsTrader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.booster = None
        self.meta: Dict = {}
        self.threshold = 0.60
        self.enabled = False
        self.mode = "paper"  # "paper" | "live"
        self.capital = 100000  # ₹ total capital
        self.risk_per_trade = 2  # % of capital per trade
        self.position: Optional[Dict] = None
        self.trades_closed: List[Dict] = []
        self.last_signal: Optional[Dict] = None
        self.last_update: Optional[str] = None
        self._load_model()

    # ---------------------------------------------------------------- model

    def _load_model(self):
        """Load the same NIFTY ML model as NiftyMLTrader."""
        try:
            import xgboost as xgb
            model_p = MODEL_PATH if MODEL_PATH.exists() else REPO_MODEL
            meta_p = META_PATH if META_PATH.exists() else REPO_META
            if model_p.exists() and meta_p.exists():
                self.booster = xgb.Booster()
                self.booster.load_model(str(model_p))
                self.meta = json.loads(meta_p.read_text())
                self.threshold = self.meta.get("threshold", 0.60)
                logger.info(
                    f"[NiftyOptions] Model loaded ({self.meta.get('model_version')}), "
                    f"thr={self.threshold}, tradeable={self.meta.get('tradeable')}"
                )
            else:
                logger.warning("[NiftyOptions] No model found — train via /api/ml-intraday/train-nifty")
        except Exception as e:
            logger.error(f"[NiftyOptions] Model load failed: {e}")

    def reload_model(self):
        self.booster = None
        self._load_model()

    @property
    def tradeable(self) -> bool:
        return bool(self.meta.get("tradeable", False))

    # ---------------------------------------------------------------- cycle

    async def run_cycle(self) -> Dict:
        """Called every 5 min during market hours."""
        if self.booster is None or not self.enabled:
            return {"status": "disabled" if self.booster else "no_model"}

        now = datetime.now(_IST)
        if not self._is_market_hours(now):
            return {"status": "market_closed"}

        try:
            feats_row, nifty_price = await asyncio.to_thread(self._latest_features)
            if feats_row is None:
                return {"status": "insufficient_data"}

            proba = self._predict(feats_row)
            self.last_update = now.strftime("%H:%M:%S")

            # 1) Manage existing position
            if self.position:
                await self._manage_position(nifty_price, now)
                return {"status": "managing", "proba": round(float(proba), 4)}

            # 2) Entry cutoff check (09:30-13:00)
            minutes_since_open = (now.hour * 60 + now.minute) - (9 * 60 + 30)
            if minutes_since_open > ENTRY_CUTOFF_MIN:
                return {"status": "past_entry_cutoff", "proba": round(float(proba), 4)}

            # 3) New entry on strong signal?
            if proba >= self.threshold:
                await self._enter(nifty_price, proba, now)
                return {"status": "entered", "proba": round(float(proba), 4)}

            return {"status": "no_signal", "proba": round(float(proba), 4)}

        except Exception as e:
            logger.error(f"[NiftyOptions] Cycle error: {e}")
            return {"status": "error", "error": str(e)}

    # ---------------------------------------------------------------- features (reuse from NIFTY model)

    def _latest_features(self):
        """Fetch recent NIFTY candles — same as NiftyMLTrader."""
        from backend.dependencies import get_angel_client
        client = get_angel_client()
        now = datetime.now(_IST)

        m5 = client.get_historical_data(
            "NSE", NIFTY_TOKEN, "FIVE_MINUTE",
            (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M"),
            now.strftime("%Y-%m-%d %H:%M"))
        m15 = client.get_historical_data(
            "NSE", NIFTY_TOKEN, "FIFTEEN_MINUTE",
            (now - timedelta(days=15)).strftime("%Y-%m-%d %H:%M"),
            now.strftime("%Y-%m-%d %H:%M"))
        m60 = client.get_historical_data(
            "NSE", NIFTY_TOKEN, "ONE_HOUR",
            (now - timedelta(days=40)).strftime("%Y-%m-%d %H:%M"),
            now.strftime("%Y-%m-%d %H:%M"))
        day = client.get_historical_data(
            "NSE", NIFTY_TOKEN, "ONE_DAY",
            (now - timedelta(days=150)).strftime("%Y-%m-%d %H:%M"),
            now.strftime("%Y-%m-%d %H:%M"))

        if m5 is None or len(m5) < 60 or day is None or len(day) < 60:
            return None, None

        for df in (m5, m15, m60, day):
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
            df.sort_values("timestamp", inplace=True)
            df.reset_index(drop=True, inplace=True)

        c = m5["close"]
        f = m5[["timestamp", "open", "high", "low", "close"]].copy()
        f["date"] = f["timestamp"].dt.date
        f["ema9_d"] = (c - _ema(c, 9)) / c * 100
        f["ema20_d"] = (c - _ema(c, 20)) / c * 100
        f["ema50_d"] = (c - _ema(c, 50)) / c * 100
        f["ema20_slope"] = _ema(c, 20).pct_change(6) * 100
        f["rsi_5m"] = _rsi(c)
        ema12, ema26 = _ema(c, 12), _ema(c, 26)
        macd = ema12 - ema26
        f["macd_hist"] = (macd - _ema(macd, 9)) / c * 100
        f["roc_3"] = c.pct_change(3) * 100
        f["roc_6"] = c.pct_change(6) * 100
        f["roc_12"] = c.pct_change(12) * 100
        f["atr_pct"] = _atr_pct(m5)
        f["z_score"] = (c - c.rolling(20).mean()) / c.rolling(20).std().replace(0, np.nan)
        f["range_pos"] = (c - m5["low"].rolling(12).min()) / (
            (m5["high"].rolling(12).max() - m5["low"].rolling(12).min()).replace(0, np.nan))
        f["candle_body"] = (c - m5["open"]) / c * 100

        day_open = f.groupby("date")["open"].transform("first")
        f["from_day_open"] = (c - day_open) / day_open * 100
        or_high = f.groupby("date")["high"].transform(lambda s: s.iloc[:3].max())
        or_low = f.groupby("date")["low"].transform(lambda s: s.iloc[:3].min())
        f["above_or"] = (c > or_high).astype(int)
        f["below_or"] = (c < or_low).astype(int)
        minutes = f["timestamp"].dt.hour * 60 + f["timestamp"].dt.minute
        f["time_since_open"] = minutes - (9 * 60 + 15)
        f["dow"] = f["timestamp"].dt.dayofweek

        c15 = m15["close"]
        m15["m15_ema20_d"] = (c15 - _ema(c15, 20)) / c15 * 100
        m15["m15_rsi"] = _rsi(c15)
        m15["m15_roc4"] = c15.pct_change(4) * 100
        m15["available_at"] = m15["timestamp"] + pd.Timedelta(minutes=15)
        f = pd.merge_asof(f.sort_values("timestamp"),
                          m15[["available_at", "m15_ema20_d", "m15_rsi", "m15_roc4"]].sort_values("available_at"),
                          left_on="timestamp", right_on="available_at", direction="backward"
                          ).drop(columns=["available_at"])

        c60 = m60["close"]
        m60["h1_ema20_d"] = (c60 - _ema(c60, 20)) / c60 * 100
        m60["h1_rsi"] = _rsi(c60)
        m60["h1_roc3"] = c60.pct_change(3) * 100
        m60["available_at"] = m60["timestamp"] + pd.Timedelta(minutes=60)
        f = pd.merge_asof(f.sort_values("timestamp"),
                          m60[["available_at", "h1_ema20_d", "h1_rsi", "h1_roc3"]].sort_values("available_at"),
                          left_on="timestamp", right_on="available_at", direction="backward"
                          ).drop(columns=["available_at"])

        cd = day["close"]
        day["d_ema20_d"] = (cd - _ema(cd, 20)) / cd * 100
        day["d_ema50_d"] = (cd - _ema(cd, 50)) / cd * 100
        day["d_rsi"] = _rsi(cd)
        day["d_ret1"] = cd.pct_change() * 100
        day["d_atr_pct"] = _atr_pct(day)
        today = datetime.now(_IST).date()
        prev = day[day["timestamp"].dt.date < today]
        if len(prev) == 0:
            return None, None
        prev_row = prev.iloc[-1]
        for col in ["d_ema20_d", "d_ema50_d", "d_rsi", "d_ret1", "d_atr_pct"]:
            f[col] = prev_row[col]
        f["gap_pct"] = (day_open - prev_row["close"]) / prev_row["close"] * 100
        f["dist_prev_high"] = (c - prev_row["high"]) / c * 100
        f["dist_prev_low"] = (c - prev_row["low"]) / c * 100
        f["above_prev_high"] = (c > prev_row["high"]).astype(int)
        f["below_prev_low"] = (c < prev_row["low"]).astype(int)

        row = f.iloc[[-1]]
        if row[NIFTY_FEATURES].isna().any(axis=1).iloc[0]:
            return None, None
        return row, float(row.iloc[0]["close"])

    def _predict(self, row: pd.DataFrame) -> float:
        import xgboost as xgb
        dm = xgb.DMatrix(row[NIFTY_FEATURES], feature_names=NIFTY_FEATURES)
        return float(self.booster.predict(dm)[0])

    # ---------------------------------------------------------------- options logic

    def _select_strike(self, nifty_price: float, direction: str, conviction: float) -> int:
        """
        Select strike based on direction and conviction level.
        direction: "CALL" (bullish) or "PUT" (bearish)
        conviction: P(success) from model, 0-1 range

        Returns: Strike price (rounded to 100)
        """
        round_to = 100
        conviction_pct = conviction * 100

        if conviction_pct >= 75:
            # Very high conviction → ATM (max gamma)
            return round(nifty_price / round_to) * round_to
        elif conviction_pct >= 65:
            # High conviction → slightly OTM (good balance)
            if direction == "CALL":
                return round((nifty_price + 50) / round_to) * round_to
            else:
                return round((nifty_price - 50) / round_to) * round_to
        else:
            # Moderate conviction → OTM (lower cost, lower prob)
            if direction == "CALL":
                return round((nifty_price + 100) / round_to) * round_to
            else:
                return round((nifty_price - 100) / round_to) * round_to

    def _select_expiry(self, conviction: float) -> str:
        """
        Select option expiry based on conviction.
        High conviction → Weekly (fast decay works for us)
        Moderate conviction → Monthly (more time)
        """
        conviction_pct = conviction * 100
        if conviction_pct >= 75:
            return "WEEKLY"  # Expires in ~4-5 days
        else:
            return "MONTHLY"  # Expires in ~28 days

    def _black_scholes(self, S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> Dict:
        """
        Calculate option Greeks using Black-Scholes model.
        S: Stock price (NIFTY level)
        K: Strike price
        T: Time to expiry (years)
        r: Risk-free rate
        sigma: Implied volatility
        option_type: "CALL" or "PUT"
        """
        if T <= 0:
            return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "premium": 0}

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        if option_type == "CALL":
            delta = norm.cdf(d1)
            premium = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:  # PUT
            delta = norm.cdf(d1) - 1
            premium = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        theta = (-(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T)) -
                 r * K * np.exp(-r * T) * norm.cdf(d2 if option_type == "CALL" else -d2))
        vega = S * norm.pdf(d1) * np.sqrt(T)

        return {
            "delta": delta,
            "gamma": gamma,
            "theta": theta / 365,  # Convert to daily
            "vega": vega / 100,  # Per 1% IV change
            "premium": premium,
        }

    async def _enter(self, nifty_price: float, proba: float, now: datetime):
        """Enter an options position."""
        from backend.dependencies import get_angel_client
        client = get_angel_client()

        # Determine direction and strike
        direction = "CALL" if proba >= 0.5 else "PUT"
        strike = self._select_strike(nifty_price, direction, proba)
        expiry = self._select_expiry(proba)

        # Estimate days to expiry (simplified)
        if expiry == "WEEKLY":
            days_to_expiry = 4  # ~weekly option
        else:
            days_to_expiry = 28  # ~monthly option

        T = days_to_expiry / 365.0

        # Calculate Greeks and premium
        greeks = self._black_scholes(
            S=nifty_price,
            K=strike,
            T=T,
            r=RISK_FREE_RATE,
            sigma=NIFTY_IMPLIED_VOL,
            option_type=direction
        )
        premium = greeks["premium"]
        delta = greeks["delta"]

        # Position sizing: Risk 2% of capital per trade
        max_loss_rupees = self.capital * (self.risk_per_trade / 100)
        # For options, stop loss is premium × 30% or max_loss_rupees
        stop_loss_premium = max(premium * 0.30, max_loss_rupees / 75)  # Assuming 75 multiplier
        quantity = max(1, int(max_loss_rupees / (stop_loss_premium * 75)))

        # Profit target: 50-100% of premium risked
        profit_target_premium = premium * 0.50

        # Symbol format: NIFTY24AUG15500CE (or PE)
        symbol = f"NIFTY{self._format_date(expiry)}{int(strike)}{'CE' if direction == 'CALL' else 'PE'}"

        order_id = None
        if self.mode == "live":
            if not self.tradeable:
                logger.warning("[NiftyOptions] LIVE blocked — model not tradeable (expectancy ≤ 0)")
                return
            try:
                token = client.search_scrip("NFO", symbol)
                if not token:
                    logger.error(f"[NiftyOptions] Could not find token for {symbol} — skipping entry")
                    return
                order_id = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: client.place_order(
                        variety="NORMAL", exchange="NFO",
                        symbol=symbol, token=token,
                        qty=quantity, order_type="MARKET",
                        transaction_type="BUY", price=0.0,
                        product="INTRADAY",
                    )
                )
                logger.info(f"[NiftyOptions] 🔴 LIVE BUY {quantity} {symbol} @ ~₹{premium:.0f} (order {order_id})")
            except Exception as e:
                logger.error(f"[NiftyOptions] LIVE order failed: {e}")
                return
        else:
            logger.info(f"[NiftyOptions] 📄 PAPER BUY {quantity} {symbol} @ ₹{premium:.0f} "
                       f"(P={proba:.2f}, Δ={delta:.2f})")

        self.position = {
            "symbol": symbol,
            "direction": direction,
            "strike": strike,
            "expiry": expiry,
            "days_to_expiry": days_to_expiry,
            "entry_nifty": nifty_price,
            "entry_premium": premium,
            "quantity": quantity,
            "delta": delta,
            "gamma": greeks["gamma"],
            "theta": greeks["theta"],
            "vega": greeks["vega"],
            "stop_loss_premium": stop_loss_premium,
            "profit_target_premium": profit_target_premium,
            "probability": round(proba * 100, 1),
            "mode": self.mode,
            "order_id": order_id,
            "opened_at": now.isoformat(),
            "max_hold_minutes": 45,
        }
        self.last_signal = {**self.position}

        self._notify(
            f"🎯 <b>NIFTY OPTIONS {'LIVE' if self.mode == 'live' else 'PAPER'} {direction}</b>\n"
            f"{symbol} ×{quantity} @ ₹{premium:.0f}\n"
            f"Strike: {strike} | Expiry: {expiry}\n"
            f"Greeks: Δ={delta:.2f} Γ={greeks['gamma']:.4f} Θ={greeks['theta']:.2f}\n"
            f"P(success)={proba:.0%}"
        )

    async def _manage_position(self, nifty_price: float, now: datetime):
        """Check exit conditions: profit target, stop loss, or Greeks shift."""
        pos = self.position
        # Update Greeks with current price
        T = (pos["days_to_expiry"] - 1) / 365.0 if pos["days_to_expiry"] > 0 else 0.01
        greeks = self._black_scholes(
            S=nifty_price,
            K=pos["strike"],
            T=T,
            r=RISK_FREE_RATE,
            sigma=NIFTY_IMPLIED_VOL,
            option_type=pos["direction"]
        )
        current_premium = greeks["premium"]
        pnl_pct = ((current_premium - pos["entry_premium"]) / pos["entry_premium"] * 100)

        reason = None
        if pnl_pct >= 50:
            reason = "profit_target"  # Hit 50% profit
        elif pnl_pct <= -30:
            reason = "stop_loss"  # Hit 30% loss
        elif abs(greeks["delta"]) < 0.30:
            reason = "delta_drop"  # Lost conviction
        elif greeks["theta"] < -0.05 and pos["days_to_expiry"] <= 3:
            reason = "theta_bleed"  # Avoid last 3 days
        elif (now - datetime.fromisoformat(pos["opened_at"])).total_seconds() > pos["max_hold_minutes"] * 60:
            reason = "time_exit"  # Max hold time
        elif now.time() >= datetime.strptime("15:10", "%H:%M").time():
            reason = "eod"  # End of day

        if not reason:
            return

        # Exit
        if self.mode == "live":
            try:
                from backend.dependencies import get_angel_client
                client = get_angel_client()
                token = client.search_scrip("NFO", pos["symbol"])
                if token:
                    oid = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: client.place_order(
                            variety="NORMAL", exchange="NFO",
                            symbol=pos["symbol"], token=token,
                            qty=pos["quantity"], order_type="MARKET",
                            transaction_type="SELL", price=0.0,
                            product="INTRADAY",
                        )
                    )
                    logger.info(f"[NiftyOptions] 🔴 LIVE SELL ({reason}, order {oid})")
            except Exception as e:
                logger.error(f"[NiftyOptions] LIVE exit failed: {e} — WILL RETRY next cycle")
                return

        closed = {
            **pos,
            "exit_nifty": nifty_price,
            "exit_premium": current_premium,
            "exit_delta": greeks["delta"],
            "pnl_pct": round(pnl_pct, 2),
            "pnl_rupees": round((current_premium - pos["entry_premium"]) * pos["quantity"] * 75, 2),
            "exit_reason": reason,
            "closed_at": now.isoformat(),
        }
        self.trades_closed.append(closed)
        self.position = None

        emoji = "🟢" if closed["pnl_pct"] >= 0 else "🔻"
        logger.info(f"[NiftyOptions] EXIT ({reason}) P&L {closed['pnl_pct']:+.2f}% "
                   f"(₹{closed['pnl_rupees']:+.0f})")
        self._notify(
            f"{emoji} <b>OPTIONS EXIT</b> ({reason})\n"
            f"{pos['symbol']}\n"
            f"P&L: {closed['pnl_pct']:+.2f}% (₹{closed['pnl_rupees']:+.0f})"
        )

    # ---------------------------------------------------------------- misc

    def _format_date(self, expiry: str) -> str:
        """Convert expiry string to date format (e.g., '24AUG')."""
        now = datetime.now(_IST)
        if expiry == "WEEKLY":
            # Next Thursday
            days_ahead = 3 - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            date = now + timedelta(days=days_ahead)
        else:
            # Last Thursday of month
            # Simplified: assume 28 days ahead
            date = now + timedelta(days=28)

        return date.strftime("%d%b").upper()

    def _notify(self, text: str):
        try:
            from backend.services import telegram_service
            telegram_service.send(text)
        except Exception:
            pass

    @staticmethod
    def _is_market_hours(now: datetime) -> bool:
        if now.weekday() >= 5:
            return False
        t = now.time()
        return (t >= datetime.strptime("09:30", "%H:%M").time()
                and t <= datetime.strptime("15:15", "%H:%M").time())

    def get_status(self) -> Dict:
        """Return complete status for API."""
        wins = [t for t in self.trades_closed if t.get("pnl_pct", 0) > 0]
        total_pnl = sum(t.get("pnl_rupees", 0) for t in self.trades_closed)

        return {
            "model_loaded": self.booster is not None,
            "model_version": self.meta.get("model_version"),
            "tradeable": self.tradeable,
            "threshold": self.threshold,
            "enabled": self.enabled,
            "mode": self.mode,
            "capital": self.capital,
            "risk_per_trade": self.risk_per_trade,
            "last_update": self.last_update,
            "position": self.position,
            "trades_closed": self.trades_closed[-20:],
            "trades_today": len(self.trades_closed),
            "win_rate": round(len(wins) / len(self.trades_closed), 3) if self.trades_closed else None,
            "total_pnl_rupees": round(total_pnl, 2),
            "test_report": self.meta.get("test_report"),
            "strategy": {
                "vehicle": "NIFTY Options",
                "entry_window": "09:30-13:00",
                "max_hold_min": 45,
                "profit_target_pct": 50,
                "stop_loss_pct": 30,
            },
        }
