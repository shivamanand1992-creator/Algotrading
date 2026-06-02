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
    "dip_threshold_pct":  1.0,       # buy when Nifty dip >= X% from prev close
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
# Position structure
# ---------------------------------------------------------------------------
#
# self._position = {
#   "active":          True,
#   "buys": [
#     { "date": "2026-06-02 09:45:00", "qty": 40, "price": 248.0,
#       "nifty_at_buy": 24100.0, "nifty_dip_pct": 1.25,
#       "order_id": "PAPER-NB-…", "invested": 9920.0 },
#     ...
#   ],
#   "total_qty":       81,
#   "total_invested":  19924.0,
#   "avg_entry_price": 246.22,
#   "mode":            "paper",
#   "last_buy_date":   "2026-06-03",   ← guard: one buy per day
#   "current_price":   255.0,
#   "unrealized_pnl":  712.38,
#   "pnl_pct":         3.57,
#   "last_checked":    "…",
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

        self._load_state()

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def _load_state(self) -> None:
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
                            setattr(self, attr, json.loads(row.value_json))
                        except Exception:
                            pass
        except Exception as exc:
            logger.warning(f"[NiftyBees] _load_state error: {exc}")

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
        if self.angel_client is None:
            return None
        try:
            loop = asyncio.get_event_loop()
            ltp  = await loop.run_in_executor(
                None, lambda: self.angel_client.get_ltp("NSE", _NIFTY_SYMBOL, _NIFTY_TOKEN)
            )
            return float(ltp) if ltp else None
        except Exception as exc:
            logger.warning(f"[NiftyBees] get_nifty_ltp error: {exc}")
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

    async def _buy(self, nb_price: float, nifty_ltp: float, dip_pct: float) -> None:
        capital  = self._config["capital_amount"]
        qty      = max(1, math.floor(capital / nb_price))
        invested = round(qty * nb_price, 2)
        mode     = self._config["mode"]
        today    = datetime.now(_IST).strftime("%Y-%m-%d")
        ts       = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S")
        order_id: Optional[str] = None

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
                return

        if order_id is None:
            order_id = f"PAPER-NB-{int(datetime.now().timestamp())}"

        buy_entry = {
            "date":          ts,
            "qty":           qty,
            "price":         round(nb_price, 2),
            "nifty_at_buy":  round(nifty_ltp, 2),
            "nifty_dip_pct": round(dip_pct, 2),
            "order_id":      order_id,
            "invested":      invested,
        }

        if self._position and self._position.get("active"):
            # Add to existing DCA position
            pos = self._position
            pos["buys"].append(buy_entry)
            pos["total_qty"]       += qty
            pos["total_invested"]   = round(pos["total_invested"] + invested, 2)
            pos["avg_entry_price"]  = round(pos["total_invested"] / pos["total_qty"], 2)
            pos["last_buy_date"]    = today
            pos["current_price"]    = round(nb_price, 2)
        else:
            self._position = {
                "active":          True,
                "buys":            [buy_entry],
                "total_qty":       qty,
                "total_invested":  invested,
                "avg_entry_price": round(nb_price, 2),
                "mode":            mode,
                "last_buy_date":   today,
                "current_price":   round(nb_price, 2),
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

    # -----------------------------------------------------------------------
    # Sell — exit entire position
    # -----------------------------------------------------------------------

    async def _sell(self, current_price: float, reason: str) -> None:
        if not self._position:
            return
        total_qty = self._position["total_qty"]
        avg_entry = self._position["avg_entry_price"]
        gain      = (current_price - avg_entry) / avg_entry * 100
        pnl       = round((current_price - avg_entry) * total_qty, 2)
        mode      = self._position["mode"]

        if mode == "live" and self.angel_client is not None:
            try:
                token = await self._resolve_niftybees_token()
                loop  = asyncio.get_event_loop()
                oid   = await loop.run_in_executor(
                    None,
                    lambda: self.angel_client.place_order(
                        variety="NORMAL", exchange="NSE",
                        symbol="NIFTYBEES-EQ", token=token,
                        qty=total_qty, order_type="MARKET",
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
            "close_reason": reason,
        }
        self._history.append(closed)
        self._position = None
        self._save_state()
        logger.info(
            f"[NiftyBees] SOLD {total_qty} units @ ₹{current_price:.2f} "
            f"| Avg Entry ₹{avg_entry:.2f} | Gain={gain:.2f}% | P&L=₹{pnl:.2f}"
        )

    # -----------------------------------------------------------------------
    # Main monitor — called every 60s from main.py during market hours
    # -----------------------------------------------------------------------

    async def run_monitor(self) -> dict:
        """
        DCA logic:
        1. If position active → update P&L; if avg gain >= target → sell ALL
        2. If Nifty dipped today and haven't bought today yet → buy chunk
        Both checks run every cycle so we can add to position on a dip day
        even while already holding units.
        """
        if not self._config.get("enabled"):
            return {"action": "none", "details": "disabled"}

        today_str = datetime.now(_IST).strftime("%Y-%m-%d")
        result    = {"action": "none", "details": ""}

        # ---- SELL CHECK ----
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
                if gain >= target:
                    await self._sell(nb_ltp, reason="target_reached")
                    return {
                        "action":  "sold",
                        "details": f"Avg gain {gain:.2f}% ≥ {target}% target — all {qty} units sold",
                        "price":   nb_ltp,
                    }

                result = {
                    "action":  "holding",
                    "details": f"Avg gain {gain:.2f}% (target {target}%)",
                    "price":   nb_ltp,
                }

        # ---- BUY CHECK: one chunk per calendar day ----
        last_buy = self._position.get("last_buy_date") if self._position else None
        if last_buy == today_str:
            return result   # already bought today, skip buy check

        prev_close = await self._get_prev_nifty_close()
        nifty_ltp  = await self._get_nifty_ltp()

        if prev_close and nifty_ltp:
            dip       = (prev_close - nifty_ltp) / prev_close * 100
            threshold = self._config["dip_threshold_pct"]
            logger.debug(f"[NiftyBees] prev_close={prev_close:.2f} ltp={nifty_ltp:.2f} dip={dip:.2f}%")

            if dip >= threshold:
                nb_ltp = await self._get_niftybees_ltp()
                if nb_ltp:
                    await self._buy(nb_ltp, nifty_ltp, dip)
                    pos = self._position
                    result = {
                        "action":         "bought",
                        "details":        f"Nifty dip {dip:.2f}% ≥ {threshold}% — buy #{len(pos['buys'])}",
                        "price":          nb_ltp,
                        "total_qty":      pos["total_qty"],
                        "avg_entry":      pos["avg_entry_price"],
                        "total_invested": pos["total_invested"],
                    }
            else:
                if result.get("action") == "none":
                    result = {
                        "action":  "watching",
                        "details": f"Nifty dip {dip:.2f}% (need {threshold}%)",
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
