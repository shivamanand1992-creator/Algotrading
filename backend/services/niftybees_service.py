"""
niftybees_service.py
====================
NiftyBees ETF autopilot — buy NIFTYBEES when Nifty drops ≥ threshold from
previous close; sell when the position gains ≥ target.

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
from sqlalchemy import Column, String, Text, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session

sys.path.append(str(Path(__file__).parent.parent.parent))

_IST = pytz.timezone("Asia/Kolkata")

# Angel One token for Nifty50 index spot price
_NIFTY_TOKEN   = "26000"
_NIFTY_SYMBOL  = "Nifty 50"

# Fallback token for NIFTYBEES ETF (Nippon India ETF Nifty BeES)
# Resolved dynamically via searchScrip; this is the known NSE token.
_NIFTYBEES_FALLBACK_TOKEN = "2850"

_DEFAULT_CONFIG: dict = {
    "enabled":            False,
    "mode":               "paper",   # "paper" | "live"
    "capital_amount":     10000.0,   # INR to deploy on each buy signal
    "dip_threshold_pct":  1.0,       # buy when Nifty intraday dip >= X%
    "target_gain_pct":    5.0,       # sell when NiftyBees position gains >= X%
}


# ---------------------------------------------------------------------------
# SQLAlchemy — reuse the same swing_service_state table
# ---------------------------------------------------------------------------

class _NBBase(DeclarativeBase):
    pass


class _NBStateRow(_NBBase):
    __tablename__ = "swing_service_state"
    key        = Column(String(64), primary_key=True)
    value_json = Column(Text,       nullable=False, default="{}")
    updated_at = Column(String(32), nullable=False, default="")

    # Allow extend_existing so other services using the same table don't clash
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
# Service
# ---------------------------------------------------------------------------

class NiftyBeesService:
    """
    Autopilot for NiftyBees ETF:
      • Every minute during 09:15–15:30 IST: check Nifty dip → buy
      • If position open: check gain → sell
    State (config + position + history) persisted in PostgreSQL.
    """

    def __init__(self, angel_client=None) -> None:
        self.angel_client = angel_client
        self._engine       = _get_engine()
        self._config: dict = _DEFAULT_CONFIG.copy()
        self._position: Optional[dict] = None
        self._history: list = []

        # daily cache for previous Nifty close
        self._prev_close_date: Optional[_date] = None
        self._prev_nifty_close: Optional[float] = None

        # cached Angel One token for NIFTYBEES
        self._niftybees_token: Optional[str] = None

        self._load_state()

    # -----------------------------------------------------------------------
    # State persistence
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
    # Config / position accessors
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
        """Mark current position as manually closed (paper only)."""
        if not self._position or not self._position.get("active"):
            return False
        self._position["active"]       = False
        self._position["close_reason"] = reason
        self._position["exit_date"]    = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S")
        self._history.append(dict(self._position))
        self._position = None
        self._save_state()
        return True

    # -----------------------------------------------------------------------
    # Market data helpers
    # -----------------------------------------------------------------------

    async def _get_prev_nifty_close(self) -> Optional[float]:
        """Return Nifty50 previous trading day close (cached per day)."""
        today = datetime.now(_IST).date()
        if self._prev_close_date == today and self._prev_nifty_close:
            return self._prev_nifty_close
        try:
            import yfinance as yf
            import pandas as pd

            loop = asyncio.get_event_loop()

            def _fetch():
                ticker = yf.Ticker("^NSEI")
                df = ticker.history(period="5d", interval="1d")
                return df

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
        """Return current Nifty50 index LTP via Angel One."""
        if self.angel_client is None:
            return None
        try:
            loop = asyncio.get_event_loop()
            ltp  = await loop.run_in_executor(
                None,
                lambda: self.angel_client.get_ltp("NSE", _NIFTY_SYMBOL, _NIFTY_TOKEN)
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
                None,
                lambda: self.angel_client.search_scrip("NSE", "NIFTYBEES")
            )
            if token:
                self._niftybees_token = token
                logger.info(f"[NiftyBees] NIFTYBEES token resolved: {token}")
                return token
        except Exception as exc:
            logger.warning(f"[NiftyBees] token resolution error: {exc}")
        self._niftybees_token = _NIFTYBEES_FALLBACK_TOKEN
        return _NIFTYBEES_FALLBACK_TOKEN

    async def _get_niftybees_ltp(self) -> Optional[float]:
        """Return current NIFTYBEES ETF LTP via Angel One, fallback to yfinance."""
        if self.angel_client is not None:
            try:
                token = await self._resolve_niftybees_token()
                loop  = asyncio.get_event_loop()
                ltp   = await loop.run_in_executor(
                    None,
                    lambda: self.angel_client.get_ltp("NSE", "NIFTYBEES-EQ", token)
                )
                if ltp and float(ltp) > 0:
                    ltp_f = float(ltp)
                    # Sanity: NIFTYBEES trades ~200-300; if > 10,000 it's paise
                    if ltp_f > 10_000:
                        ltp_f /= 100.0
                    return ltp_f
            except Exception as exc:
                logger.warning(f"[NiftyBees] AngelOne NIFTYBEES LTP error: {exc}")

        # yfinance fallback
        try:
            import yfinance as yf
            loop = asyncio.get_event_loop()

            def _fetch():
                t  = yf.Ticker("NIFTYBEES.NS")
                df = t.history(period="1d", interval="1m")
                return df

            df = await loop.run_in_executor(None, _fetch)
            if df is not None and not df.empty:
                return float(df["Close"].iloc[-1])
        except Exception as exc:
            logger.warning(f"[NiftyBees] yfinance NIFTYBEES LTP error: {exc}")
        return None

    # -----------------------------------------------------------------------
    # Buy / sell logic
    # -----------------------------------------------------------------------

    async def _buy(self, niftybees_price: float, nifty_ltp: float, dip_pct: float) -> None:
        capital  = self._config["capital_amount"]
        qty      = max(1, math.floor(capital / niftybees_price))
        invested = round(qty * niftybees_price, 2)
        mode     = self._config["mode"]
        order_id: Optional[str] = None

        if mode == "live" and self.angel_client is not None:
            try:
                token = await self._resolve_niftybees_token()
                loop  = asyncio.get_event_loop()
                order_id = await loop.run_in_executor(
                    None,
                    lambda: self.angel_client.place_order(
                        variety="NORMAL",
                        exchange="NSE",
                        symbol="NIFTYBEES-EQ",
                        token=token,
                        qty=qty,
                        order_type="MARKET",
                        transaction_type="BUY",
                        price=0.0,
                        product="DELIVERY",
                    )
                )
                logger.info(f"[NiftyBees] Live BUY order placed: {order_id}")
            except Exception as exc:
                logger.error(f"[NiftyBees] Live BUY failed: {exc}")
                return

        if order_id is None:
            order_id = f"PAPER-NB-{int(datetime.now().timestamp())}"

        self._position = {
            "active":         True,
            "symbol":         "NIFTYBEES",
            "qty":            qty,
            "entry_price":    round(niftybees_price, 2),
            "entry_date":     datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S"),
            "nifty_at_entry": round(nifty_ltp, 2),
            "nifty_dip_pct":  round(dip_pct, 2),
            "current_price":  round(niftybees_price, 2),
            "mode":           mode,
            "order_id":       order_id,
            "invested":       invested,
            "unrealized_pnl": 0.0,
            "pnl_pct":        0.0,
            "last_checked":   datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save_state()
        logger.info(
            f"[NiftyBees] BOUGHT {qty} units @ ₹{niftybees_price:.2f} "
            f"| Nifty dip={dip_pct:.2f}% | Invested=₹{invested:.0f}"
        )

    async def _sell(self, current_price: float, reason: str) -> None:
        if not self._position:
            return
        qty   = self._position["qty"]
        entry = self._position["entry_price"]
        gain  = (current_price - entry) / entry * 100
        pnl   = round((current_price - entry) * qty, 2)
        mode  = self._position["mode"]

        if mode == "live" and self.angel_client is not None:
            try:
                token = await self._resolve_niftybees_token()
                loop  = asyncio.get_event_loop()
                oid   = await loop.run_in_executor(
                    None,
                    lambda: self.angel_client.place_order(
                        variety="NORMAL",
                        exchange="NSE",
                        symbol="NIFTYBEES-EQ",
                        token=token,
                        qty=qty,
                        order_type="MARKET",
                        transaction_type="SELL",
                        price=0.0,
                        product="DELIVERY",
                    )
                )
                logger.info(f"[NiftyBees] Live SELL order placed: {oid}")
            except Exception as exc:
                logger.error(f"[NiftyBees] Live SELL failed: {exc}")
                return

        closed = {
            **self._position,
            "active":        False,
            "exit_price":    round(current_price, 2),
            "exit_date":     datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S"),
            "gain_pct":      round(gain, 2),
            "realized_pnl":  pnl,
            "close_reason":  reason,
        }
        self._history.append(closed)
        self._position = None
        self._save_state()
        logger.info(
            f"[NiftyBees] SOLD {qty} units @ ₹{current_price:.2f} "
            f"| Gain={gain:.2f}% | P&L=₹{pnl:.2f}"
        )

    # -----------------------------------------------------------------------
    # Main monitor — called every 60s during market hours from main.py
    # -----------------------------------------------------------------------

    async def run_monitor(self) -> dict:
        """
        Check conditions and act:
        1. If position open → check gain threshold → sell
        2. If no position  → check dip threshold  → buy
        Returns a dict describing what action was taken (if any).
        """
        result = {"action": "none", "details": ""}

        if not self._config.get("enabled"):
            return result

        # ---- sell check ----
        if self._position and self._position.get("active"):
            nb_ltp = await self._get_niftybees_ltp()
            if nb_ltp:
                entry   = self._position["entry_price"]
                gain    = (nb_ltp - entry) / entry * 100
                # Update live P&L in position dict
                qty     = self._position["qty"]
                self._position["current_price"]  = round(nb_ltp, 2)
                self._position["unrealized_pnl"] = round((nb_ltp - entry) * qty, 2)
                self._position["pnl_pct"]        = round(gain, 2)
                self._position["last_checked"]   = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S")
                self._save_state()

                target = self._config["target_gain_pct"]
                if gain >= target:
                    await self._sell(nb_ltp, reason="target_reached")
                    result = {
                        "action":  "sold",
                        "details": f"Gain {gain:.2f}% ≥ {target}% target",
                        "price":   nb_ltp,
                    }
                else:
                    result = {
                        "action":  "holding",
                        "details": f"Gain {gain:.2f}% (target {target}%)",
                        "price":   nb_ltp,
                    }
            return result

        # ---- buy check ----
        prev_close = await self._get_prev_nifty_close()
        nifty_ltp  = await self._get_nifty_ltp()

        if prev_close and nifty_ltp:
            dip = (prev_close - nifty_ltp) / prev_close * 100
            logger.debug(f"[NiftyBees] Nifty prev_close={prev_close:.2f} ltp={nifty_ltp:.2f} dip={dip:.2f}%")
            threshold = self._config["dip_threshold_pct"]

            if dip >= threshold:
                nb_ltp = await self._get_niftybees_ltp()
                if nb_ltp:
                    await self._buy(nb_ltp, nifty_ltp, dip)
                    result = {
                        "action":  "bought",
                        "details": f"Nifty dip {dip:.2f}% ≥ {threshold}% threshold",
                        "price":   nb_ltp,
                    }
            else:
                result = {
                    "action":  "watching",
                    "details": f"Nifty dip {dip:.2f}% (need {threshold}%)",
                }

        return result


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_svc: Optional[NiftyBeesService] = None


def get_niftybees_service(angel_client=None) -> NiftyBeesService:
    global _svc
    if _svc is None:
        _svc = NiftyBeesService(angel_client)
    elif angel_client is not None and _svc.angel_client is None:
        _svc.angel_client = angel_client
    return _svc
