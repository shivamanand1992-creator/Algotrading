"""
NIFTY ML Auto-Trader

Runs the trained NIFTY direction model live and executes via NIFTYBEES ETF
through Angel One. Paper mode by default; live mode auto-punches real orders
but ONLY if the model's out-of-sample after-cost expectancy is positive.

Strategy (validated on 2018-2026 data):
- Entries: 09:30–13:00 only, when P(success) >= trained threshold (0.60)
- Target +0.8% / SL -0.4% on NIFTY, managed on 5-min closes
- Max hold 210 min; hard square-off 15:10
- One position at a time
"""

import json
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, List

import numpy as np
import pandas as pd
from loguru import logger

from backend.ml.nifty_model import (
    MODEL_PATH, META_PATH, NIFTY_FEATURES, TARGET_PCT, SL_PCT,
    HOLD_CANDLES, ENTRY_CUTOFF_MIN, _ema, _rsi, _atr_pct,
)

_IST = timezone(timedelta(hours=5, minutes=30))

# Repo-shipped fallback model (committed after local training on 11yr data)
REPO_MODEL = Path(__file__).parent / "storage" / "nifty_xgb.json"
REPO_META = Path(__file__).parent / "storage" / "nifty_meta.json"

NIFTY_TOKEN = "26000"        # NSE NIFTY 50 index
NIFTYBEES_SYMBOL = "NIFTYBEES-EQ"


class NiftyMLTrader:
    """Singleton: live NIFTY model inference + NIFTYBEES execution."""

    _instance = None

    @classmethod
    def get_instance(cls) -> "NiftyMLTrader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.booster = None
        self.meta: Dict = {}
        self.threshold = 0.60
        self.enabled = False
        self.mode = "paper"              # "paper" | "live"
        self.capital = 100000            # ₹ per trade for sizing
        self.position: Optional[Dict] = None
        self.trades_closed: List[Dict] = []
        self.last_signal: Optional[Dict] = None
        self.last_proba: Optional[float] = None
        self.last_update: Optional[str] = None
        self._niftybees_token: Optional[str] = None
        self._load_model()

    # ---------------------------------------------------------------- model

    def _load_model(self):
        try:
            import xgboost as xgb
            # Prefer freshly trained model on Railway volume; fall back to repo-shipped
            model_p = MODEL_PATH if MODEL_PATH.exists() else REPO_MODEL
            meta_p = META_PATH if META_PATH.exists() else REPO_META
            if model_p.exists() and meta_p.exists():
                self.booster = xgb.Booster()
                self.booster.load_model(str(model_p))
                self.meta = json.loads(meta_p.read_text())
                self.threshold = self.meta.get("threshold", 0.60)
                logger.info(
                    f"[NiftyTrader] Model loaded ({self.meta.get('model_version')}) from "
                    f"{model_p}, thr={self.threshold}, tradeable={self.meta.get('tradeable')}"
                )
            else:
                logger.warning("[NiftyTrader] No model found — train via /api/ml-intraday/train-nifty")
        except Exception as e:
            logger.error(f"[NiftyTrader] Model load failed: {e}")

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
            self.last_proba = round(float(proba), 4)
            self.last_update = now.strftime("%H:%M:%S")

            # 1) Manage open position first
            if self.position:
                await self._manage_position(nifty_price, now)
                return {"status": "managing", "proba": self.last_proba}

            # 2) Hard square-off window / entry cutoff
            minutes_since_open = (now.hour * 60 + now.minute) - (9 * 60 + 15)
            if minutes_since_open > ENTRY_CUTOFF_MIN:
                return {"status": "past_entry_cutoff", "proba": self.last_proba}

            # 3) New entry?
            if proba >= self.threshold:
                await self._enter(nifty_price, proba, now)
                return {"status": "entered", "proba": self.last_proba}

            return {"status": "no_signal", "proba": self.last_proba}

        except Exception as e:
            logger.error(f"[NiftyTrader] Cycle error: {e}")
            return {"status": "error", "error": str(e)}

    # ---------------------------------------------------------------- features

    def _latest_features(self):
        """Fetch recent NIFTY candles from Angel One and build one feature row."""
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

        # 15m context (completed candles)
        c15 = m15["close"]
        m15["m15_ema20_d"] = (c15 - _ema(c15, 20)) / c15 * 100
        m15["m15_rsi"] = _rsi(c15)
        m15["m15_roc4"] = c15.pct_change(4) * 100
        m15["available_at"] = m15["timestamp"] + pd.Timedelta(minutes=15)
        f = pd.merge_asof(f.sort_values("timestamp"),
                          m15[["available_at", "m15_ema20_d", "m15_rsi", "m15_roc4"]].sort_values("available_at"),
                          left_on="timestamp", right_on="available_at", direction="backward"
                          ).drop(columns=["available_at"])

        # 60m context
        c60 = m60["close"]
        m60["h1_ema20_d"] = (c60 - _ema(c60, 20)) / c60 * 100
        m60["h1_rsi"] = _rsi(c60)
        m60["h1_roc3"] = c60.pct_change(3) * 100
        m60["available_at"] = m60["timestamp"] + pd.Timedelta(minutes=60)
        f = pd.merge_asof(f.sort_values("timestamp"),
                          m60[["available_at", "h1_ema20_d", "h1_rsi", "h1_roc3"]].sort_values("available_at"),
                          left_on="timestamp", right_on="available_at", direction="backward"
                          ).drop(columns=["available_at"])

        # Daily context — previous day only
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

    # ---------------------------------------------------------------- execution

    def _resolve_niftybees_token(self, client) -> Optional[str]:
        if self._niftybees_token is None:
            self._niftybees_token = client.search_scrip("NSE", "NIFTYBEES")
        return self._niftybees_token

    async def _enter(self, nifty_price: float, proba: float, now: datetime):
        from backend.dependencies import get_angel_client
        client = get_angel_client()

        # NIFTYBEES price for sizing
        token = self._resolve_niftybees_token(client)
        bees_ltp = client.get_ltp("NSE", "NIFTYBEES-EQ", token) if token else None
        if not bees_ltp:
            logger.error("[NiftyTrader] Could not price NIFTYBEES — skipping entry")
            return
        qty = max(1, int(self.capital / bees_ltp))

        order_id = None
        if self.mode == "live":
            if not self.tradeable:
                logger.warning("[NiftyTrader] LIVE blocked — model not tradeable (expectancy ≤ 0)")
                return
            try:
                loop = asyncio.get_event_loop()
                order_id = await loop.run_in_executor(None, lambda: client.place_order(
                    variety="NORMAL", exchange="NSE",
                    symbol=NIFTYBEES_SYMBOL, token=token,
                    qty=qty, order_type="MARKET",
                    transaction_type="BUY", price=0.0,
                    product="INTRADAY",
                ))
                logger.info(f"[NiftyTrader] 🔴 LIVE BUY {qty} NIFTYBEES @ ~₹{bees_ltp} (order {order_id})")
            except Exception as e:
                logger.error(f"[NiftyTrader] LIVE order failed: {e}")
                return
        else:
            logger.info(f"[NiftyTrader] 📄 PAPER BUY {qty} NIFTYBEES @ ₹{bees_ltp} (P={proba:.2f})")

        self.position = {
            "entry_nifty": nifty_price,
            "entry_bees": bees_ltp,
            "qty": qty,
            "target_nifty": round(nifty_price * (1 + TARGET_PCT / 100), 2),
            "sl_nifty": round(nifty_price * (1 - SL_PCT / 100), 2),
            "probability": round(proba * 100, 1),
            "mode": self.mode,
            "order_id": order_id,
            "opened_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=HOLD_CANDLES * 5)).isoformat(),
        }
        self.last_signal = {**self.position}
        self._notify(f"🎯 <b>NIFTY ML {'LIVE' if self.mode == 'live' else 'PAPER'} BUY</b>\n"
                     f"NIFTYBEES ×{qty} @ ₹{bees_ltp}\n"
                     f"NIFTY {nifty_price} → T {self.position['target_nifty']} / "
                     f"SL {self.position['sl_nifty']}\nP(success)={proba:.0%}")

    async def _manage_position(self, nifty_price: float, now: datetime):
        pos = self.position
        reason = None
        if nifty_price <= pos["sl_nifty"]:
            reason = "sl"
        elif nifty_price >= pos["target_nifty"]:
            reason = "target"
        elif now >= datetime.fromisoformat(pos["expires_at"]):
            reason = "time"
        elif now.time() >= datetime.strptime("15:10", "%H:%M").time():
            reason = "eod"
        if not reason:
            return

        from backend.dependencies import get_angel_client
        client = get_angel_client()
        token = self._resolve_niftybees_token(client)
        bees_ltp = client.get_ltp("NSE", "NIFTYBEES-EQ", token) if token else pos["entry_bees"]

        if pos["mode"] == "live":
            try:
                loop = asyncio.get_event_loop()
                oid = await loop.run_in_executor(None, lambda: client.place_order(
                    variety="NORMAL", exchange="NSE",
                    symbol=NIFTYBEES_SYMBOL, token=token,
                    qty=pos["qty"], order_type="MARKET",
                    transaction_type="SELL", price=0.0,
                    product="INTRADAY",
                ))
                logger.info(f"[NiftyTrader] 🔴 LIVE SELL {pos['qty']} NIFTYBEES ({reason}, order {oid})")
            except Exception as e:
                logger.error(f"[NiftyTrader] LIVE exit failed: {e} — WILL RETRY next cycle")
                return  # keep position; retry next cycle

        pnl_pct = (bees_ltp - pos["entry_bees"]) / pos["entry_bees"] * 100
        pnl_rs = (bees_ltp - pos["entry_bees"]) * pos["qty"]
        closed = {**pos, "exit_bees": bees_ltp, "exit_nifty": nifty_price,
                  "pnl_pct": round(pnl_pct, 3), "pnl_rs": round(pnl_rs, 2),
                  "exit_reason": reason, "closed_at": now.isoformat()}
        self.trades_closed.append(closed)
        self.position = None
        logger.info(f"[NiftyTrader] EXIT ({reason}) P&L {pnl_pct:+.2f}% (₹{pnl_rs:+.0f})")
        self._notify(f"{'🟢' if pnl_pct >= 0 else '🔻'} <b>NIFTY ML EXIT</b> ({reason})\n"
                     f"P&L: {pnl_pct:+.2f}% (₹{pnl_rs:+.0f})")

    async def force_exit(self):
        if self.position:
            now = datetime.now(_IST)
            self.position["expires_at"] = now.isoformat()
            feats = None
            try:
                _, price = await asyncio.to_thread(self._latest_features)
            except Exception:
                price = self.position["entry_nifty"]
            await self._manage_position(price or self.position["entry_nifty"], now)

    # ---------------------------------------------------------------- misc

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
        wins = [t for t in self.trades_closed if t["pnl_pct"] > 0]
        return {
            "model_loaded": self.booster is not None,
            "model_version": self.meta.get("model_version"),
            "tradeable": self.tradeable,
            "threshold": self.threshold,
            "enabled": self.enabled,
            "mode": self.mode,
            "capital": self.capital,
            "last_update": self.last_update,
            "last_proba": self.last_proba,
            "position": self.position,
            "trades_closed": self.trades_closed[-20:],
            "trades_today": len(self.trades_closed),
            "win_rate": round(len(wins) / len(self.trades_closed), 3) if self.trades_closed else None,
            "total_pnl_rs": round(sum(t["pnl_rs"] for t in self.trades_closed), 2),
            "test_report": self.meta.get("test_report"),
            "val_report": self.meta.get("val_report"),
            "strategy": {
                "target_pct": TARGET_PCT, "sl_pct": SL_PCT,
                "max_hold_min": HOLD_CANDLES * 5,
                "entry_window": "09:30-13:00", "vehicle": "NIFTYBEES ETF",
            },
        }
