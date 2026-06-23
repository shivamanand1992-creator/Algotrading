"""
Portfolio Service
=================
Fetches all demat holdings from Angel One broker, enriches with live prices,
and computes invested value vs market value for the full portfolio view.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
from loguru import logger

sys.path.append(str(Path(__file__).parent.parent.parent))

_IST = pytz.timezone("Asia/Kolkata")

_DEMO_HOLDINGS: List[Dict[str, Any]] = [
    {
        "symbol": "RELIANCE",
        "name": "Reliance Industries",
        "isin": "INE002A01018",
        "qty": 10,
        "avg_price": 2450.0,
        "current_price": 2580.0,
        "invested_value": 24500.0,
        "market_value": 25800.0,
        "pnl": 1300.0,
        "pnl_pct": 5.31,
        "token": "2885",
        "exchange": "NSE",
        "instrument_type": "EQ",
    },
    {
        "symbol": "TCS",
        "name": "Tata Consultancy Services",
        "isin": "INE467B01029",
        "qty": 5,
        "avg_price": 3500.0,
        "current_price": 3620.0,
        "invested_value": 17500.0,
        "market_value": 18100.0,
        "pnl": 600.0,
        "pnl_pct": 3.43,
        "token": "11536",
        "exchange": "NSE",
        "instrument_type": "EQ",
    },
    {
        "symbol": "NIFTYBEES",
        "name": "Nifty BeES ETF",
        "isin": "INF204KA1B21",
        "qty": 50,
        "avg_price": 240.0,
        "current_price": 252.0,
        "invested_value": 12000.0,
        "market_value": 12600.0,
        "pnl": 600.0,
        "pnl_pct": 5.0,
        "token": "2850",
        "exchange": "NSE",
        "instrument_type": "ETF",
    },
    {
        "symbol": "HDFCBANK",
        "name": "HDFC Bank",
        "isin": "INE040A01034",
        "qty": 8,
        "avg_price": 1650.0,
        "current_price": 1590.0,
        "invested_value": 13200.0,
        "market_value": 12720.0,
        "pnl": -480.0,
        "pnl_pct": -3.64,
        "token": "1333",
        "exchange": "NSE",
        "instrument_type": "EQ",
    },
    {
        "symbol": "INFY",
        "name": "Infosys",
        "isin": "INE009A01021",
        "qty": 12,
        "avg_price": 1420.0,
        "current_price": 1510.0,
        "invested_value": 17040.0,
        "market_value": 18120.0,
        "pnl": 1080.0,
        "pnl_pct": 6.34,
        "token": "1594",
        "exchange": "NSE",
        "instrument_type": "EQ",
    },
]

_FRIENDLY_NAMES: Dict[str, str] = {
    "RELIANCE": "Reliance Industries",
    "TCS": "Tata Consultancy Services",
    "INFY": "Infosys",
    "HDFCBANK": "HDFC Bank",
    "ICICIBANK": "ICICI Bank",
    "SBIN": "State Bank of India",
    "AXISBANK": "Axis Bank",
    "KOTAKBANK": "Kotak Mahindra Bank",
    "BAJFINANCE": "Bajaj Finance",
    "WIPRO": "Wipro",
    "ADANIPORTS": "Adani Ports",
    "HINDUNILVR": "Hindustan Unilever",
    "TATAMOTORS": "Tata Motors",
    "MARUTI": "Maruti Suzuki",
    "ASIANPAINT": "Asian Paints",
    "NIFTYBEES": "Nifty BeES ETF",
    "BANKBEES": "Bank BeES ETF",
    "GOLDBEES": "Gold BeES ETF",
    "JUNIORBEES": "Junior BeES ETF",
    "ITBEES": "Nifty IT BeES ETF",
    "PHARMABEES": "Pharma BeES ETF",
    "CPSE": "CPSE ETF",
    "LIQUIDBEES": "Liquid BeES ETF",
}


def _friendly_name(symbol: str) -> str:
    return _FRIENDLY_NAMES.get(symbol.upper(), symbol)


def _summary(holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_invested = sum(h["invested_value"] for h in holdings)
    total_market   = sum(h["market_value"] for h in holdings)
    total_pnl      = total_market - total_invested
    total_pnl_pct  = (total_pnl / total_invested * 100) if total_invested else 0.0
    return {
        "total_invested":     round(total_invested, 2),
        "total_market_value": round(total_market, 2),
        "total_pnl":          round(total_pnl, 2),
        "total_pnl_pct":      round(total_pnl_pct, 2),
    }


class PortfolioService:
    def __init__(self, angel_client) -> None:
        self._angel = angel_client
        self._last_sync: Optional[datetime] = None
        self._holdings: List[Dict[str, Any]] = []

    async def sync(self) -> Dict[str, Any]:
        from backend.config import DEMO_MODE
        if DEMO_MODE:
            return {"holdings": _DEMO_HOLDINGS, **_summary(_DEMO_HOLDINGS), "last_sync": None}

        if self._angel is None:
            return {"holdings": [], "error": "broker_not_connected", **_summary([])}

        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(None, self._angel.get_holdings)
        except Exception as exc:
            logger.error(f"[Portfolio] get_holdings failed: {exc}")
            return {"holdings": self._holdings, "error": str(exc), **_summary(self._holdings)}

        if not isinstance(raw, list):
            logger.warning(f"[Portfolio] get_holdings returned {type(raw).__name__}")
            return {"holdings": self._holdings, **_summary(self._holdings)}

        logger.info(f"[Portfolio] {len(raw)} total holding(s) from broker")

        enriched: List[Dict[str, Any]] = []
        for row in raw:
            sym       = (row.get("tradingsymbol") or "").replace("-EQ", "").replace("-BE", "").upper()
            qty       = int(row.get("quantity") or 0)
            avg_price = float(row.get("averageprice") or 0.0)
            token     = str(row.get("symboltoken") or "")
            isin      = row.get("isin", "")
            exchange  = (row.get("exchange") or "NSE").upper()
            itype     = (row.get("instrumenttype") or "EQ").upper()

            if qty <= 0 or avg_price <= 0:
                continue

            cur_price = await self._get_price(sym, token, exchange)
            if not cur_price or cur_price <= 0:
                cur_price = avg_price

            invested  = round(avg_price * qty, 2)
            market_v  = round(cur_price * qty, 2)
            pnl       = round(market_v - invested, 2)
            pnl_pct   = round((pnl / invested) * 100, 2) if invested else 0.0

            enriched.append({
                "symbol":          sym,
                "name":            _friendly_name(sym),
                "isin":            isin,
                "qty":             qty,
                "avg_price":       round(avg_price, 2),
                "current_price":   round(cur_price, 2),
                "invested_value":  invested,
                "market_value":    market_v,
                "pnl":             pnl,
                "pnl_pct":         pnl_pct,
                "token":           token,
                "exchange":        exchange,
                "instrument_type": itype,
            })

        enriched.sort(key=lambda x: x["market_value"], reverse=True)
        self._holdings  = enriched
        self._last_sync = datetime.now(_IST)

        return {
            "holdings": enriched,
            **_summary(enriched),
            "last_sync": self._last_sync.strftime("%d %b %Y %H:%M IST"),
        }

    def get_cached(self) -> Dict[str, Any]:
        from backend.config import DEMO_MODE
        if DEMO_MODE:
            return {"holdings": _DEMO_HOLDINGS, **_summary(_DEMO_HOLDINGS), "last_sync": None}
        return {
            "holdings": self._holdings,
            **_summary(self._holdings),
            "last_sync": self._last_sync.strftime("%d %b %Y %H:%M IST") if self._last_sync else None,
        }

    async def _get_price(self, symbol: str, token: str, exchange: str = "NSE") -> Optional[float]:
        loop = asyncio.get_event_loop()

        if self._angel and token:
            try:
                ltp = await loop.run_in_executor(
                    None, self._angel.get_ltp, exchange, symbol, token
                )
                if ltp and float(ltp) > 0:
                    return float(ltp)
            except Exception as exc:
                logger.debug(f"[Portfolio] LTP failed for {symbol}: {exc}")

        try:
            import yfinance as yf

            def _fetch():
                t     = yf.Ticker(f"{symbol}.NS")
                info  = getattr(t, "fast_info", None)
                price = None
                if info:
                    price = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
                return float(price) if price else None

            price = await loop.run_in_executor(None, _fetch)
            if price and price > 0:
                return price
        except Exception as exc:
            logger.debug(f"[Portfolio] yfinance fallback failed for {symbol}: {exc}")

        return None


_svc_instance: Optional[PortfolioService] = None


def get_portfolio_service(angel_client=None) -> PortfolioService:
    global _svc_instance
    if _svc_instance is None:
        _svc_instance = PortfolioService(angel_client)
    elif angel_client is not None and _svc_instance._angel is None:
        _svc_instance._angel = angel_client
    return _svc_instance
