"""
niftybees_service.py
====================
NiftyBees ETF autopilot — DCA buy strategy:
  • Each trading day Nifty drops ≥ threshold% from previous close → buy a chunk
  • Tracks blended average cost across all buys
  • Sells ALL units when average gain ≥ target%
  • No "one position at a time" restriction — accumulates across days

Paper mode  — positions tracked in DB; no real orders
Live mode   — CNC DELIVERY orders via Angel One
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime, date as _date
from pathlib import Path
from typing import Optional

import pytz
from loguru import logger
from sqlalchemy import Column, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

sys.path.append(str(Path(__file__).parent.parent.parent))

_IST = pytz.timezone("Asia/Kolkata")

_NIFTY_TOKEN   = "26000"
_NIFTY_SYMBOL  = "Nifty 50"
_NIFTYBEES_FALLBACK_TOKEN = "2850"

_DEFAULT_CONFIG: dict = {
    "enabled":            False,
    "mode":               "paper",   # "paper" | "live"
    "capital_amount":     10000.0,   # INR per buy chunk
    "dip_threshold_pct":  1.0,       # buy when Nifty dip >= X% from day high
    "target_gain_pct":    5.0,       # sell ALL when avg gain >= X%
}


# ---------------------------------------------------------------------------
# SQLAlchemy — reuse swing_service_state table with niftybees_* keys
# ---------------------------------------------------------------------------

class _NBBase(DeclarativeBase):
    pass


class _NBStateRow(_NBBase):
    __tablename__ = "swing_service_state"
    key        = Column(String(64), primary_key=True)
    value_json = Column(Text,       nullable=False, default="{}")
    updated_at = Column(String(32), nullable=False, default="")
    __table_args__ = {"extend_existing": True}


def _get_engine():
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        logs_dir = Path(__file__).parent.parent.parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{logs_dir}/trades.db"
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, echo=False, future=True, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# Position structure with audit trail
# ---------------------------------------------------------------------------
#
# self._position = {
#   "active":              True,
#   "buys": [
#     { "date": "2026-06-02 09:45:00", "qty": 40, "price": 248.0,
#       "nifty_at_buy": 24100.0, "nifty_dip_pct": 1.25,
#       "dip_level": 1,  ← 1st dip from day high, 2nd dip, etc.
#       "trigger_reason": "1st dip from day high",
#       "source": "system",  ← "system" or "manual"
#       "order_id": "PAPER-NB-…", "invested": 9920.0 },
#     ...
#   ],
#   "system_qty":          40,  ← qty bought by system only
#   "manual_qty":          50,  ← qty bought manually (not sold by system)
#   "total_qty":           90,  ← system + manual
#   "total_invested":      19924.0,
#   "avg_entry_price":     246.22,
#   "mode":                "paper",
#   "day_high":            24500.0,  ← today's NIFTY high
#   "day_high_date":       "2026-06-02",
#   "current_price":       255.0,
#   "unrealized_pnl":      712.38,
#   "pnl_pct":             3.57,
#   "last_checked":        "…",
# }

class NiftyBeesService:
    def __init__(self, angel_client=None) -> None:
        self.angel_client = angel_client
        self._engine       = _get_engine()
        self._config: dict = _DEFAULT_CONFIG.copy()
        self._position: Optional[dict] = None
        self._history: list = []

        self._prev_close_date: Optional[_date] = None
        self._prev_nifty_close: Optional[float] = None
        self._niftybees_token: Optional[str] = None
        self._today_nifty_high: Optional[float] = None  # Track day high for dip detection
        self._dips_bought_today: list = []  # Track which dip levels we've bought (1st, 2nd, 3rd, etc.)

        self._load_state()

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load state from DB with up to 3 retries — Railway cold-start safety."""
        for attempt in range(3):
            try:
                _NBBase.metadata.create_all(self._engine, checkfirst=True)
                with Session(self._engine) as s:
                    for key, attr in [
                        ("niftybees_config",   "_config"),
                        ("niftybees_position", "_position"),
                        ("niftybees_history",  "_history"),
                    ]:
                        row = s.get(_NBStateRow, key)
                        if row and row.value_json:
                            try:
                                val = json.loads(row.value_json)
                                if val is not None:
                                    setattr(self, attr, val)
                            except Exception:
                                pass
                pos  = self._position
                enab = self._config.get("enabled", False)
                logger.info(
                    f"[NiftyBees] State loaded from DB "
                    f"(attempt {attempt+1}) — "
                    f"enabled={enab}, "
                    f"position={'ACTIVE (' + str(pos.get('total_qty', '?')) + ' units, ' + str(len(pos.get('buys', []))) + ' buys)' if pos and pos.get('active') else 'none'}, "
                    f"history={len(self._history)} trade(s)"
                )
                return
            except Exception as exc:
                logger.warning(f"[NiftyBees] DB load attempt {attempt+1}/3 failed: {exc}")
                if attempt < 2:
                    time.sleep(2)
        logger.error("[NiftyBees] All DB load attempts failed — running with empty state")

    def _save_state(self) -> None:
        try:
            now_str = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S")
            with Session(self._engine) as s:
                for key, val in [
                    ("niftybees_config",   self._config),
                    ("niftybees_position", self._position),
                    ("niftybees_history",  self._history),
                ]:
                    row = s.get(_NBStateRow, key)
                    if row is None:
                        row = _NBStateRow(key=key, value_json=json.dumps(val), updated_at=now_str)
                        s.add(row)
                    else:
                        row.value_json = json.dumps(val)
                        row.updated_at = now_str
                s.commit()
        except Exception as exc:
            logger.warning(f"[NiftyBees] _save_state error: {exc}")

    # -----------------------------------------------------------------------
    # Config / public API
    # -----------------------------------------------------------------------

    def set_config(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if k in _DEFAULT_CONFIG:
                self._config[k] = v
        self._save_state()
        logger.info(f"[NiftyBees] Config updated: {self._config}")

    def get_status(self) -> dict:
        return {
            "config":   self._config,
            "position": self._position,
            "history":  self._history[-20:],
        }

    def close_position_manual(self, reason: str = "manual_close") -> bool:
        if not self._position or not self._position.get("active"):
            return False
        closed = {
            **self._position,
            "active":       False,
            "exit_price":   self._position.get("current_price", self._position.get("avg_entry_price", 0)),
            "exit_date":    datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S"),
            "gain_pct":     self._position.get("pnl_pct", 0.0),
            "realized_pnl": self._position.get("unrealized_pnl", 0.0),
            "close_reason": reason,
        }
        self._history.append(closed)
        self._position = None
        self._save_state()
        return True

    # -----------------------------------------------------------------------
    # Market data helpers
    # -----------------------------------------------------------------------

    async def _get_prev_nifty_close(self) -> Optional[float]:
        today = datetime.now(_IST).date()
        if self._prev_close_date == today and self._prev_nifty_close:
            return self._prev_nifty_close
        try:
            import yfinance as yf
            import pandas as pd

            loop = asyncio.get_event_loop()

            def _fetch():
                return yf.Ticker("^NSEI").history(period="5d", interval="1d")

            df = await loop.run_in_executor(None, _fetch)
            if df is None or df.empty:
                return None

            df.index = pd.to_datetime(df.index).date
            past_days = sorted([d for d in df.index if d < today])
            if not past_days:
                return None

            close = float(df.loc[past_days[-1], "Close"])
            self._prev_close_date  = today
            self._prev_nifty_close = close
            logger.debug(f"[NiftyBees] Prev Nifty close = ₹{close:.2f} ({past_days[-1]})")
            return close
        except Exception as exc:
            logger.error(f"[NiftyBees] prev_nifty_close error: {exc}")
            return None

    async def _get_nifty_ltp(self) -> Optional[float]:
        # Try Angel One first
        if self.angel_client is not None:
            try:
                loop = asyncio.get_event_loop()
                ltp  = await loop.run_in_executor(
                    None, lambda: self.angel_client.get_ltp("NSE", _NIFTY_SYMBOL, _NIFTY_TOKEN)
                )
                if ltp:
                    return float(ltp)
            except Exception as exc:
                logger.warning(f"[NiftyBees] get_nifty_ltp Angel One error: {exc} — trying yfinance fallback")

        # yfinance fallback — fetches latest intraday price for Nifty 50
        try:
            import yfinance as yf
            loop = asyncio.get_event_loop()
            def _yf_ltp():
                df = yf.download("^NSEI", period="1d", interval="1m", progress=False, auto_adjust=True)
                if df.empty:
                    return None
                return float(df["Close"].iloc[-1])
            ltp = await loop.run_in_executor(None, _yf_ltp)
            if ltp:
                logger.debug(f"[NiftyBees] Nifty LTP via yfinance fallback: ₹{ltp:.2f}")
                return ltp
        except Exception as exc:
            logger.warning(f"[NiftyBees] get_nifty_ltp yfinance fallback error: {exc}")

        return None

    async def _detect_gap_down_open(self, nifty_ltp: float) -> bool:
        """Check if today opened with a gap-down > threshold% from previous close."""
        today = datetime.now(_IST).date()
        # Only check at market open (once per day)
        if self._position and self._position.get("day_high_date") == str(today):
            return False  # Already checked today

        prev_close = await self._get_prev_nifty_close()
        if not prev_close:
            return False

        gap_down = (prev_close - nifty_ltp) / prev_close * 100
        threshold = self._config["dip_threshold_pct"]

        return gap_down >= threshold

    async def _get_nifty_day_high(self) -> Optional[float]:
        """Fetch today's NIFTY high. Resets daily at 9:15 AM IST."""
        today = datetime.now(_IST).date()
        if self._today_nifty_high and self._position and self._position.get("day_high_date") == str(today):
            return self._today_nifty_high

        try:
            import yfinance as yf
            loop = asyncio.get_event_loop()
            def _yf_day_high():
                df = yf.download("^NSEI", period="1d", interval="1m", progress=False, auto_adjust=True)
                if df.empty or "High" not in df.columns:
                    return None
                return float(df["High"].max())
            high = await loop.run_in_executor(None, _yf_day_high)
            if high:
                self._today_nifty_high = high
                logger.debug(f"[NiftyBees] Today's Nifty high: ₹{high:.2f}")
                return high
        except Exception as exc:
            logger.warning(f"[NiftyBees] get_nifty_day_high error: {exc}")

        return None

    async def _resolve_niftybees_token(self) -> str:
        if self._niftybees_token:
            return self._niftybees_token
        if self.angel_client is None:
            return _NIFTYBEES_FALLBACK_TOKEN
        try:
            loop  = asyncio.get_event_loop()
            token = await loop.run_in_executor(
                None, lambda: self.angel_client.search_scrip("NSE", "NIFTYBEES")
            )
            if token:
                self._niftybees_token = token
                return token
        except Exception as exc:
            logger.warning(f"[NiftyBees] token resolution error: {exc}")
        self._niftybees_token = _NIFTYBEES_FALLBACK_TOKEN
        return _NIFTYBEES_FALLBACK_TOKEN

    async def _get_niftybees_ltp(self) -> Optional[float]:
        if self.angel_client is not None:
            try:
                token = await self._resolve_niftybees_token()
                loop  = asyncio.get_event_loop()
                ltp   = await loop.run_in_executor(
                    None, lambda: self.angel_client.get_ltp("NSE", "NIFTYBEES-EQ", token)
                )
                if ltp and float(ltp) > 0:
                    ltp_f = float(ltp)
                    if ltp_f > 10_000:   # sanity: NIFTYBEES ~200-300; paise guard
                        ltp_f /= 100.0
                    return ltp_f
            except Exception as exc:
                logger.warning(f"[NiftyBees] AngelOne NIFTYBEES LTP error: {exc}")

        # yfinance fallback
        try:
            import yfinance as yf
            loop = asyncio.get_event_loop()
            df   = await loop.run_in_executor(
                None, lambda: yf.Ticker("NIFTYBEES.NS").history(period="1d", interval="1m")
            )
            if df is not None and not df.empty:
                return float(df["Close"].iloc[-1])
        except Exception as exc:
            logger.warning(f"[NiftyBees] yfinance NIFTYBEES LTP error: {exc}")
        return None

    # -----------------------------------------------------------------------
    # Buy — add a chunk to the DCA position
    # -----------------------------------------------------------------------

    async def _buy(self, nb_price: float, nifty_ltp: float, dip_pct: float, dip_level: int = 1, trigger_reason: str = "dip from day high") -> None:
        capital  = self._config["capital_amount"]
        qty      = max(1, math.floor(capital / nb_price))
        invested = round(qty * nb_price, 2)
        mode     = self._config["mode"]
        today    = datetime.now(_IST).strftime("%Y-%m-%d")
        ts       = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S")
        order_id: Optional[str] = None

        if mode == "live" and self.angel_client is None:
            logger.error("[NiftyBees] Live BUY skipped — Angel One not connected.")
            try:
                from backend.services.telegram_service import send, is_configured
                if is_configured():
                    send(
                        f"⚠️ <b>JARVIS — Manual Action Required</b>\n\n"
                        f"Nifty is down <b>{dip_pct:.2f}%</b> "
                        f"(₹{nifty_ltp:,.0f} vs prev close)\n"
                        f"NiftyBees price: ₹{nb_price:.2f}\n\n"
                        f"<b>Could not place order — broker not connected.</b>\n\n"
                        f"Please buy <b>{qty} units of NIFTYBEES</b> manually in Angel One app."
                    )
            except Exception:
                pass
            return

        if mode == "live" and self.angel_client is not None:
            try:
                token = await self._resolve_niftybees_token()
                loop  = asyncio.get_event_loop()
                order_id = await loop.run_in_executor(
                    None,
                    lambda: self.angel_client.place_order(
                        variety="NORMAL", exchange="NSE",
                        symbol="NIFTYBEES-EQ", token=token,
                        qty=qty, order_type="MARKET",
                        transaction_type="BUY", price=0.0,
                        product="DELIVERY",
                    )
                )
            except Exception as exc:
                logger.error(f"[NiftyBees] Live BUY failed: {exc}")
                try:
                    from backend.services.telegram_service import send, is_configured
                    if is_configured():
                        send(
                            f"⚠️ <b>JARVIS — Manual Action Required</b>\n\n"
                            f"Nifty is down <b>{dip_pct:.2f}%</b> "
                            f"(₹{nifty_ltp:,.0f} vs prev close)\n"
                            f"NiftyBees price: ₹{nb_price:.2f}\n\n"
                            f"<b>Could not place order — Angel One API error:</b>\n"
                            f"<code>{exc}</code>\n\n"
                            f"Please buy <b>{qty} units of NIFTYBEES</b> manually in Angel One app."
                        )
                except Exception:
                    pass
                return

        if order_id is None:
            order_id = f"PAPER-NB-{int(datetime.now().timestamp())}"

        buy_entry = {
            "date":            ts,
            "qty":             qty,
            "price":           round(nb_price, 2),
            "nifty_at_buy":    round(nifty_ltp, 2),
            "nifty_dip_pct":   round(dip_pct, 2),
            "dip_level":       dip_level,  # 1st, 2nd, 3rd dip, etc.
            "trigger_reason":  trigger_reason,  # e.g., "1st dip from day high", "gap-down open"
            "source":          "system",  # system-bought vs manual
            "order_id":        order_id,
            "invested":        invested,
        }

        if self._position and self._position.get("active"):
            # Add to existing DCA position
            pos = self._position
            pos["buys"].append(buy_entry)
            pos["total_qty"]       += qty
            pos["system_qty"]       = pos.get("system_qty", 0) + qty
            pos["total_invested"]   = round(pos["total_invested"] + invested, 2)
            pos["avg_entry_price"]  = round(pos["total_invested"] / pos["total_qty"], 2)
            pos["last_buy_date"]    = today
            pos["current_price"]    = round(nb_price, 2)
            pos["day_high"]         = max(pos.get("day_high", nifty_ltp), nifty_ltp)
            pos["day_high_date"]    = today
        else:
            self._position = {
                "active":          True,
                "buys":            [buy_entry],
                "system_qty":      qty,  # track system-bought qty separately
                "manual_qty":      0,    # manual buys not tracked here, for audit purposes
                "total_qty":       qty,
                "total_invested":  invested,
                "avg_entry_price": round(nb_price, 2),
                "mode":            mode,
                "last_buy_date":   today,
                "current_price":   round(nb_price, 2),
                "day_high":        nifty_ltp,
                "day_high_date":   today,
                "unrealized_pnl":  0.0,
                "pnl_pct":         0.0,
                "last_checked":    ts,
            }

        self._save_state()
        pos = self._position
        logger.info(
            f"[NiftyBees] BUY #{len(pos['buys'])} — {qty} units @ ₹{nb_price:.2f} "
            f"| total_qty={pos['total_qty']} | avg_entry=₹{pos['avg_entry_price']:.2f} "
            f"| total_invested=₹{pos['total_invested']:.0f}"
        )

        # Send Telegram notification
        try:
            from backend.services.telegram_service import send, is_configured
            if is_configured():
                msg = (
                    f"🟢 <b>NIFTYBEES BUY #{len(pos['buys'])}</b>\n\n"
                    f"<b>Buy Details:</b>\n"
                    f"• Qty: <b>{qty} units</b>\n"
                    f"• Price: <b>₹{nb_price:.2f}</b>\n"
                    f"• Invested: ₹{invested:,.0f}\n\n"
                    f"<b>Trigger:</b>\n"
                    f"• {trigger_reason}\n"
                    f"• NIFTY dip: <b>{dip_pct:.2f}%</b>\n"
                    f"• NIFTY price: ₹{nifty_ltp:,.0f}\n\n"
                    f"<b>Position Summary:</b>\n"
                    f"• Total units: {pos['total_qty']}\n"
                    f"• Avg entry: ₹{pos['avg_entry_price']:.2f}\n"
                    f"• Total invested: ₹{pos['total_invested']:,.0f}\n"
                    f"• Mode: {mode.upper()}\n\n"
                    f"🎯 Target: 5% gain (sell at ₹{pos['avg_entry_price'] * 1.05:.2f})"
                )
                send(msg)
        except Exception as exc:
            logger.warning(f"[NiftyBees] Telegram notification failed: {exc}")

    # -----------------------------------------------------------------------
    # Sell — exit entire position
    # -----------------------------------------------------------------------

    async def _sell(self, current_price: float, reason: str) -> None:
        if not self._position:
            return
        system_qty = self._position.get("system_qty", self._position["total_qty"])
        total_qty  = self._position["total_qty"]
        avg_entry  = self._position["avg_entry_price"]
        gain       = (current_price - avg_entry) / avg_entry * 100
        pnl        = round((current_price - avg_entry) * system_qty, 2)  # P&L only on system-bought qty
        mode       = self._position["mode"]

        # Log what's being sold vs kept
        manual_qty = total_qty - system_qty
        if manual_qty > 0:
            logger.info(
                f"[NiftyBees] Selling system-bought units only: "
                f"{system_qty} system + {manual_qty} manual (kept for manual trading)"
            )

        if mode == "live" and self.angel_client is not None:
            try:
                token = await self._resolve_niftybees_token()
                loop  = asyncio.get_event_loop()
                oid   = await loop.run_in_executor(
                    None,
                    lambda: self.angel_client.place_order(
                        variety="NORMAL", exchange="NSE",
                        symbol="NIFTYBEES-EQ", token=token,
                        qty=system_qty, order_type="MARKET",
                        transaction_type="SELL", price=0.0,
                        product="DELIVERY",
                    )
                )
                logger.info(f"[NiftyBees] Live SELL order: {oid}")
            except Exception as exc:
                logger.error(f"[NiftyBees] Live SELL failed: {exc}")
                return

        closed = {
            **self._position,
            "active":       False,
            "exit_price":   round(current_price, 2),
            "exit_date":    datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S"),
            "gain_pct":     round(gain, 2),
            "realized_pnl": pnl,
            "units_sold":   system_qty,  # only system-bought units were sold
            "units_kept":   manual_qty,  # manual units kept in demat for manual trading
            "close_reason": reason,
        }
        self._history.append(closed)

        # If manual units remain, update position to reflect that
        if manual_qty > 0:
            self._position["active"]   = False  # system position closed
            self._position["total_qty"] = manual_qty
            self._position["system_qty"] = 0  # all system units sold
        else:
            self._position = None

        self._save_state()
        logger.info(
            f"[NiftyBees] SOLD {system_qty} system units @ ₹{current_price:.2f} "
            f"| Avg Entry ₹{avg_entry:.2f} | Gain={gain:.2f}% | P&L=₹{pnl:.2f} | "
            f"Manual units kept: {manual_qty}"
        )

        # Send Telegram notification
        try:
            from backend.services.telegram_service import send, is_configured
            if is_configured():
                emoji = "🟢" if pnl >= 0 else "🔴"
                msg = (
                    f"{emoji} <b>NIFTYBEES SOLD</b> — Target Reached! 🎯\n\n"
                    f"<b>Exit Details:</b>\n"
                    f"• Units sold: <b>{system_qty}</b>\n"
                    f"• Exit price: <b>₹{current_price:.2f}</b>\n"
                    f"• Avg entry: ₹{avg_entry:.2f}\n\n"
                    f"<b>P&L Summary:</b>\n"
                    f"• Gain: <b>{gain:.2f}%</b>\n"
                    f"• Realized P&L: <b>₹{pnl:,.0f}</b>\n"
                    f"• Total invested: ₹{total_qty * avg_entry:,.0f}\n\n"
                )
                if manual_qty > 0:
                    msg += (
                        f"<b>Remaining Position:</b>\n"
                        f"• Manual units: {manual_qty} (kept for manual trading)\n\n"
                    )
                msg += f"<b>Trade closed:</b> {reason.replace('_', ' ').title()}"
                send(msg)
        except Exception as exc:
            logger.warning(f"[NiftyBees] Telegram sell notification failed: {exc}")

    # -----------------------------------------------------------------------
    # Main monitor — called every 60s from main.py during market hours
    # -----------------------------------------------------------------------

    async def run_monitor(self) -> dict:
        """
        Enhanced DCA logic with day-high tracking:
        1. If position active → update P&L; if avg gain >= target → sell system-bought units
        2. Track Nifty day high (resets daily at 9:15 AM)
        3. Buy on every 1% dip from day high (1st dip, 2nd dip, etc.)
        4. Audit trail tracks: when, at what price, what dip level, system vs manual
        """
        if not self._config.get("enabled"):
            return {"action": "none", "details": "disabled"}

        today_str = datetime.now(_IST).strftime("%Y-%m-%d")
        result    = {"action": "none", "details": ""}

        # ---- SELL CHECK: sell when avg gain >= target ----
        if self._position and self._position.get("active"):
            nb_ltp = await self._get_niftybees_ltp()
            if nb_ltp:
                avg    = self._position["avg_entry_price"]
                qty    = self._position["total_qty"]
                gain   = (nb_ltp - avg) / avg * 100
                self._position["current_price"]  = round(nb_ltp, 2)
                self._position["unrealized_pnl"] = round((nb_ltp - avg) * qty, 2)
                self._position["pnl_pct"]        = round(gain, 2)
                self._position["last_checked"]   = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S")
                self._save_state()

                target = self._config["target_gain_pct"]
                if gain >= target and self._position.get("system_qty", 0) > 0:
                    await self._sell(nb_ltp, reason="target_reached")
                    system_qty = self._position.get("system_qty", 0) if self._position else 0
                    return {
                        "action":  "sold",
                        "details": f"Avg gain {gain:.2f}% ≥ {target}% target — {system_qty} system units sold",
                        "price":   nb_ltp,
                    }

                result = {
                    "action":  "holding",
                    "details": f"Avg gain {gain:.2f}% (target {target}%)",
                    "price":   nb_ltp,
                }

        # ---- BUY CHECK: multiple dips per day from day high ----
        # Fetch current Nifty price and day high
        nifty_ltp  = await self._get_nifty_ltp()
        day_high   = await self._get_nifty_day_high()

        if nifty_ltp and day_high:
            threshold     = self._config["dip_threshold_pct"]

            # Reset dips_bought_today if day changed
            if self._position and self._position.get("day_high_date") != today_str:
                self._dips_bought_today = []

            # Check for gap-down open first (before calculating dip from day high)
            is_gap_down = await self._detect_gap_down_open(nifty_ltp)
            if is_gap_down and 0 not in self._dips_bought_today:  # Use dip_level=0 for gap-down
                nb_ltp = await self._get_niftybees_ltp()
                if nb_ltp:
                    prev_close = await self._get_prev_nifty_close()
                    gap_pct = ((prev_close - nifty_ltp) / prev_close) * 100
                    await self._buy(nb_ltp, nifty_ltp, gap_pct, dip_level=0, trigger_reason="gap-down open")
                    self._dips_bought_today.append(0)
                    pos = self._position
                    result = {
                        "action":         "bought",
                        "details":        f"Gap-down open {gap_pct:.2f}% — first buy at open",
                        "price":          nb_ltp,
                        "total_qty":      pos["total_qty"],
                        "system_qty":     pos.get("system_qty", pos["total_qty"]),
                        "avg_entry":      pos["avg_entry_price"],
                        "total_invested": pos["total_invested"],
                    }

            # Now check dips from day high
            dip_from_high = ((day_high - nifty_ltp) / day_high) * 100
            logger.debug(
                f"[NiftyBees] day_high={day_high:.2f} ltp={nifty_ltp:.2f} "
                f"dip_from_high={dip_from_high:.2f}% (threshold={threshold}%)"
            )

            # Determine which dip level this is (1st = 1%, 2nd = 2%, etc.)
            dip_level = int(dip_from_high / threshold)
            if dip_level < 1:
                dip_level = 1

            # Buy if we haven't already bought at this dip level
            if dip_from_high >= threshold and dip_level not in self._dips_bought_today:
                nb_ltp = await self._get_niftybees_ltp()
                if nb_ltp:
                    ordinals = {1: '1st', 2: '2nd', 3: '3rd', 4: '4th', 5: '5th'}
                    ordinal = ordinals.get(dip_level, f'{dip_level}th')
                    trigger_reason = f"{ordinal} dip from day high"
                    await self._buy(nb_ltp, nifty_ltp, dip_from_high, dip_level=dip_level, trigger_reason=trigger_reason)
                    self._dips_bought_today.append(dip_level)
                    pos = self._position
                    result = {
                        "action":         "bought",
                        "details":        f"Nifty {dip_from_high:.2f}% below day high — {trigger_reason}",
                        "price":          nb_ltp,
                        "total_qty":      pos["total_qty"],
                        "system_qty":     pos.get("system_qty", pos["total_qty"]),
                        "avg_entry":      pos["avg_entry_price"],
                        "total_invested": pos["total_invested"],
                    }
            else:
                if result.get("action") == "none":
                    result = {
                        "action":  "watching",
                        "details": f"Nifty {dip_from_high:.2f}% below day high (need {threshold}%)",
                    }

        return result


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_svc: Optional[NiftyBeesService] = None


def get_niftybees_service(angel_client=None) -> NiftyBeesService:
    global _svc
    if _svc is None:
        _svc = NiftyBeesService(angel_client)
    elif angel_client is not None and _svc.angel_client is None:
        _svc.angel_client = angel_client
    return _svc
