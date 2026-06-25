"""
ETF Holdings Service
====================
Syncs ETF holdings from Angel One broker, tracks a configurable profit target
per ETF, auto-sells ALL units when target is hit, and sends Telegram alerts.

ETF detection rules (applied to tradingsymbol):
  • ends with "BEES"   — NIFTYBEES, BANKBEES, JUNIORBEES, ITBEES, PHARMABEES …
  • ends with "ETF"    — GOLDETF, SILVRETF, PSUBNKBEES …
  • instrumenttype in {"AMFI", "ETF", "MUTUALFUND"}
  • any symbol on a known ETF whitelist

Live price: Angel One LTP first; yfinance {symbol}.NS fallback if API is degraded.
Demo mode: returns hardcoded mock holdings.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
from loguru import logger

sys.path.append(str(Path(__file__).parent.parent.parent))

_IST = pytz.timezone("Asia/Kolkata")

_DEFAULT_PROFIT_TARGET_PCT = 50.0
_CONFIG_FILE = Path(__file__).parent.parent.parent / "data" / "etf_config.json"


def _load_target_pct() -> float:
    try:
        if _CONFIG_FILE.exists():
            data = json.loads(_CONFIG_FILE.read_text())
            return float(data.get("target_gain_pct", _DEFAULT_PROFIT_TARGET_PCT))
    except Exception:
        pass
    return _DEFAULT_PROFIT_TARGET_PCT


def _save_target_pct(pct: float) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps({"target_gain_pct": pct}))


def get_profit_target_pct() -> float:
    return _load_target_pct()


def set_profit_target_pct(pct: float) -> None:
    if pct <= 0 or pct > 100:
        raise ValueError(f"target_gain_pct must be between 0 and 100, got {pct}")
    _save_target_pct(pct)

# Symbols explicitly known to be ETFs (fallback list when instrumenttype is missing)
_ETF_SUFFIXES  = ("BEES", "ETF", "IETF", "FUND")
_ETF_KEYWORDS  = ("GOLDETF", "SILVRETF", "NIFTYETF", "NIFTYGOLD", "PSUBNK")

# Map tradingsymbol → yfinance ticker for price fallback
_YF_MAP: Dict[str, str] = {
    "NIFTYBEES":   "NIFTYBEES.NS",
    "BANKBEES":    "BANKBEES.NS",
    "JUNIORBEES":  "JUNIORBEES.NS",
    "ITBEES":      "ITBEES.NS",
    "PHARMABEES":  "PHARMABEES.NS",
    "GOLDBEES":    "GOLDBEES.NS",
    "LIQUIDBEES":  "LIQUIDBEES.NS",
    "CPSE":        "CPSEETF.NS",
    "PSUBNKBEES":  "PSUBNKBEES.NS",
    "MOM100":      "MOM100.NS",
    "MAFANG":      "MAFANG.NS",
    "NV20":        "NV20BEES.NS",
}


def _is_etf(row: dict) -> bool:
    # Angel One returns tradingsymbol as "NIFTYBEES-EQ" — strip the -EQ suffix
    raw_sym = (row.get("tradingsymbol") or "").upper()
    sym     = raw_sym.replace("-EQ", "").replace("-BE", "")
    itype   = (row.get("instrumenttype") or "").upper()

    if itype in {"AMFI", "ETF", "MUTUALFUND"}:
        return True
    for sfx in _ETF_SUFFIXES:
        if sym.endswith(sfx):
            return True
    for kw in _ETF_KEYWORDS:
        if kw in sym:
            return True
    return False


def _yf_ticker(symbol: str) -> str:
    return _YF_MAP.get(symbol.upper(), f"{symbol.upper()}.NS")


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

_DEMO_HOLDINGS = [
    {
        "symbol":        "NIFTYBEES",
        "name":          "Nifty BeES",
        "qty":           50,
        "avg_price":     240.50,
        "current_price": 252.80,
        "pnl":           615.0,
        "pnl_pct":       5.11,
        "target_price":  252.53,
        "target_hit":    True,
        "token":         "2850",
        "exchange":      "NSE",
    },
    {
        "symbol":        "BANKBEES",
        "name":          "Bank BeES",
        "qty":           20,
        "avg_price":     430.00,
        "current_price": 440.10,
        "pnl":           202.0,
        "pnl_pct":       2.35,
        "target_price":  451.50,
        "target_hit":    False,
        "token":         "1594",
        "exchange":      "NSE",
    },
    {
        "symbol":        "GOLDBEES",
        "name":          "Gold BeES",
        "qty":           15,
        "avg_price":     560.00,
        "current_price": 575.50,
        "pnl":           232.5,
        "pnl_pct":       2.77,
        "target_price":  588.00,
        "target_hit":    False,
        "token":         "1064",
        "exchange":      "NSE",
    },
]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ETFHoldingsService:
    """
    One singleton per process.  angel_client may be None (paper / demo).
    """

    def __init__(self, angel_client) -> None:
        self._angel = angel_client
        self._last_sync: Optional[datetime] = None
        self._holdings: List[Dict[str, Any]] = []

    # ── Public API ────────────────────────────────────────────────────────

    async def sync_and_check(self) -> Dict[str, Any]:
        """
        1. Fetch holdings from broker (or yfinance for price if LTP fails).
        2. Compute P&L for each ETF holding.
        3. Auto-sell any holding at/above 5% target.
        Returns summary dict with holding list + any sell actions taken.
        """
        from backend.config import DEMO_MODE
        if DEMO_MODE:
            return {"holdings": _DEMO_HOLDINGS, "sells": []}

        if self._angel is None:
            return {"holdings": [], "sells": [], "error": "broker_not_connected"}

        loop   = asyncio.get_event_loop()
        raw    = await loop.run_in_executor(None, self._angel.get_holdings)
        if not isinstance(raw, list):
            logger.warning(f"[ETFHoldings] get_holdings returned {type(raw).__name__} — skipping.")
            return {"holdings": self._holdings, "sells": []}

        logger.info(
            f"[ETFHoldings] {len(raw)} total holding(s) from broker: "
            + ", ".join(
                f"{r.get('tradingsymbol','?')}({r.get('instrumenttype','?')})"
                for r in raw
            )
        )
        etfs = [r for r in raw if _is_etf(r)]
        logger.info(f"[ETFHoldings] {len(etfs)} ETF(s) detected after filter.")
        if not etfs:
            self._holdings = []
            return {"holdings": [], "sells": []}

        enriched: List[Dict[str, Any]] = []
        sells: List[str] = []

        for row in etfs:
            sym       = (row.get("tradingsymbol") or "").replace("-EQ", "").upper()
            qty       = int(row.get("quantity") or 0)
            avg_price = float(row.get("averageprice") or 0.0)
            token     = str(row.get("symboltoken") or "")

            if qty <= 0 or avg_price <= 0:
                continue

            # --- current price ---
            cur_price = await self._get_price(sym, token)
            if cur_price is None or cur_price <= 0:
                cur_price = avg_price   # fallback to cost price — show 0% gain

            pnl     = (cur_price - avg_price) * qty
            pnl_pct = ((cur_price - avg_price) / avg_price) * 100.0

            target_pct   = get_profit_target_pct()
            target_price = round(avg_price * (1 + target_pct / 100), 2)
            target_hit   = cur_price >= target_price

            entry = {
                "symbol":        sym,
                "name":          _friendly_name(sym),
                "qty":           qty,
                "avg_price":     round(avg_price, 2),
                "current_price": round(cur_price, 2),
                "pnl":           round(pnl, 2),
                "pnl_pct":       round(pnl_pct, 2),
                "target_price":  target_price,
                "target_hit":    target_hit,
                "token":         token,
                "exchange":      "NSE",
            }
            enriched.append(entry)

            # --- auto-sell on target ---
            if target_hit:
                sold = await self._sell(sym, qty, token, cur_price, pnl_pct)
                if sold:
                    sells.append(sym)

        self._holdings = enriched
        self._last_sync = datetime.now(_IST)
        return {"holdings": enriched, "sells": sells}

    def get_cached(self) -> List[Dict[str, Any]]:
        """Return last synced holding list without hitting the broker."""
        from backend.config import DEMO_MODE
        if DEMO_MODE:
            return _DEMO_HOLDINGS
        return self._holdings

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _get_price(self, symbol: str, token: str) -> Optional[float]:
        loop = asyncio.get_event_loop()

        # 1. Angel One LTP
        if self._angel and token:
            try:
                ltp = await loop.run_in_executor(
                    None, self._angel.get_ltp, "NSE", symbol, token
                )
                if ltp and ltp > 0:
                    return float(ltp)
            except Exception as exc:
                logger.debug(f"[ETFHoldings] LTP failed for {symbol}: {exc}")

        # 2. yfinance fallback
        try:
            yf_sym = _yf_ticker(symbol)
            import yfinance as yf
            def _fetch():
                df = yf.download(yf_sym, period="1d", interval="1m",
                                  progress=False, auto_adjust=True)
                if df.empty:
                    return None
                return float(df["Close"].iloc[-1])
            price = await loop.run_in_executor(None, _fetch)
            if price and price > 0:
                logger.debug(f"[ETFHoldings] yfinance price for {symbol}: {price}")
                return price
        except Exception as exc:
            logger.warning(f"[ETFHoldings] yfinance fallback failed for {symbol}: {exc}")

        return None

    async def _sell(self, symbol: str, qty: int, token: str,
                    cur_price: float, pnl_pct: float) -> bool:
        """Place a CNC DELIVERY SELL order.  Sends Telegram alert regardless of outcome."""
        from backend.services.telegram_service import send

        mode_str = "live"
        order_id = None

        try:
            if self._angel is None:
                raise RuntimeError("broker not connected")

            loop = asyncio.get_event_loop()

            # Angel One needs "<SYMBOL>-EQ" for cash equity sell
            sell_sym = f"{symbol}-EQ"

            order_id = await loop.run_in_executor(
                None,
                lambda: self._angel.place_order(
                    variety        = "NORMAL",
                    exchange       = "NSE",
                    symbol         = sell_sym,
                    token          = token,
                    qty            = qty,
                    order_type     = "MARKET",
                    transaction_type = "SELL",
                    price          = 0.0,
                    trigger_price  = 0.0,
                    product        = "DELIVERY",
                )
            )
            logger.info(
                f"[ETFHoldings] AUTO-SELL {qty} × {symbol} @ ≈₹{cur_price:.2f} "
                f"(+{pnl_pct:.2f}%) — order_id={order_id}"
            )
        except Exception as exc:
            logger.error(f"[ETFHoldings] Sell order FAILED for {symbol}: {exc}")
            mode_str = "FAILED"

        # Telegram notification regardless of success
        target_pct = get_profit_target_pct()
        if mode_str == "live":
            msg = (
                f"✅ <b>JARVIS — ETF Target Hit!</b>\n\n"
                f"Sold <b>{qty} × {symbol}</b>\n"
                f"Gain: <b>+{pnl_pct:.2f}%</b> (target {target_pct:.1f}%)\n"
                f"Price: ₹{cur_price:.2f}\n"
                f"P&amp;L: ₹{(cur_price - (cur_price / (1 + pnl_pct / 100))) * qty:,.0f}\n"
                f"Order ID: {order_id}"
            )
        else:
            msg = (
                f"⚠️ <b>JARVIS — ETF Target Hit (Manual Action Required)</b>\n\n"
                f"<b>{symbol}</b> is up <b>+{pnl_pct:.2f}%</b> — target {target_pct:.1f}% reached!\n"
                f"Qty: {qty} units at ₹{cur_price:.2f}\n\n"
                f"Auto-sell FAILED — please sell manually in Angel One."
            )
        try:
            send(msg)
        except Exception:
            pass

        return mode_str == "live"


def _friendly_name(symbol: str) -> str:
    _names = {
        "NIFTYBEES":  "Nifty 50 BeES",
        "BANKBEES":   "Bank BeES",
        "JUNIORBEES": "Junior BeES (Midcap)",
        "ITBEES":     "Nifty IT BeES",
        "PHARMABEES": "Pharma BeES",
        "GOLDBEES":   "Gold BeES",
        "LIQUIDBEES": "Liquid BeES",
        "CPSE":       "CPSE ETF",
        "PSUBNKBEES": "PSU Bank BeES",
        "MOM100":     "Momentum 100",
        "MAFANG":     "MAFANG ETF",
        "NV20":       "NV20 BeES",
    }
    return _names.get(symbol.upper(), symbol)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_svc_instance: Optional[ETFHoldingsService] = None


def get_etf_holdings_service(angel_client=None) -> ETFHoldingsService:
    global _svc_instance
    if _svc_instance is None:
        _svc_instance = ETFHoldingsService(angel_client)
    elif angel_client is not None and _svc_instance._angel is None:
        _svc_instance._angel = angel_client
    return _svc_instance
