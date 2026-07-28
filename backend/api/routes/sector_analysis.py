"""
Sector & Index Rotation Analysis API routes.

GET  /api/sectors/analysis   — run (or return cached) full sector scan
POST /api/sectors/refresh    — force fresh scan (invalidate cache)
GET  /api/sectors/cycle      — just the market cycle phase (instant)
"""
import asyncio
from fastapi import APIRouter, HTTPException

from backend.config import DEMO_MODE

router = APIRouter(prefix="/api/sectors", tags=["sectors"])

# ── Demo data ────────────────────────────────────────────────────────────────

_DEMO_RESULT = {
    "cycle": {
        "phase": "expansion",
        "description": "Bull market expansion — cyclicals, banks, mid-caps historically lead.",
        "advice": "Favour high-beta sectors: Banks, Midcap, Auto, Infra, Metal.",
        "nifty_price": 23450.0,
        "nifty_ret_1m": 2.1,
        "nifty_ret_3m": 5.8,
        "nifty_ret_6m": 9.4,
        "nifty_ret_12m": 14.2,
        "above_ema200": True,
        "ema200": 22100.0,
    },
    "sectors": [
        {"id": "bank",   "name": "Banking & Finance",      "theme": "Financials",  "etf": "BANKBEES.NS", "etf_name": "Bank BeES",      "rank": 1, "signal": "BUY",        "total_score": 0.78, "momentum_score": 0.35, "technical_score": 0.30, "cycle_score": 0.225, "ret_4w": 1.2, "ret_12w": 8.2, "ret_26w": 12.1, "ret_4w_vs_nifty": 0.5, "ret_12w_vs_nifty": 2.4, "ret_26w_vs_nifty": 2.7, "rsi": 62, "adx": 28, "macd_hist": 0.12, "above_e10": True, "above_e26": True, "above_e52": True, "ema_aligned": True, "reasons": ["12W +2.4% vs Nifty (strong)", "Price > EMA10 > EMA26 > EMA52 (aligned)", "RSI=62 (bullish momentum zone)", "ADX=28 (clear weekly trend)", "Historically strong in expansion phase"], "data_error": False},
        {"id": "midcap", "name": "Nifty Midcap 100",       "theme": "Broad Market","etf": "JUNIORBEES.NS","etf_name": "Junior BeES",    "rank": 2, "signal": "BUY",        "total_score": 0.74, "momentum_score": 0.33, "technical_score": 0.185, "cycle_score": 0.225, "ret_4w": 1.8, "ret_12w": 9.5, "ret_26w": 15.3, "ret_4w_vs_nifty": 1.1, "ret_12w_vs_nifty": 3.7, "ret_26w_vs_nifty": 5.9, "rsi": 59, "adx": 24, "macd_hist": 0.08, "above_e10": True, "above_e26": True, "above_e52": True, "ema_aligned": True, "reasons": ["4W +1.1% vs Nifty", "12W +3.7% vs Nifty (strong)", "Price > EMA10 > EMA26 > EMA52 (aligned)", "RSI=59 (momentum zone)", "Historically strong in expansion phase"], "data_error": False},
        {"id": "it",     "name": "Information Technology", "theme": "Technology",  "etf": "ITBEES.NS",   "etf_name": "Nifty IT ETF",   "rank": 3, "signal": "ACCUMULATE", "total_score": 0.56, "momentum_score": 0.23, "technical_score": 0.145, "cycle_score": 0.1875,"ret_4w": 0.5, "ret_12w": 4.2, "ret_26w": 7.0, "ret_4w_vs_nifty": -0.7, "ret_12w_vs_nifty": -1.6, "ret_26w_vs_nifty": -2.4, "rsi": 54, "adx": 19, "macd_hist": 0.03, "above_e10": True, "above_e26": True, "above_e52": False, "ema_aligned": False, "reasons": ["Price > EMA26 (mid-term uptrend)", "RSI=54 (neutral)", "Lags Nifty by -2.4% on 26W basis"], "data_error": False},
        {"id": "auto",   "name": "Automobiles",            "theme": "Consumer Discretionary", "etf": None, "etf_name": None,           "rank": 4, "signal": "ACCUMULATE", "total_score": 0.52, "momentum_score": 0.20, "technical_score": 0.11,  "cycle_score": 0.2125,"ret_4w": 0.3, "ret_12w": 3.5, "ret_26w": 6.8, "ret_4w_vs_nifty": -0.9, "ret_12w_vs_nifty": -2.3, "ret_26w_vs_nifty": -2.6, "rsi": 51, "adx": 18, "macd_hist": 0.02, "above_e10": True, "above_e26": True, "above_e52": False, "ema_aligned": False, "reasons": ["Price > EMA26", "Lags Nifty by -2.6% on 26W basis", "Historically strong in expansion phase"], "data_error": False},
        {"id": "pharma", "name": "Pharma & Healthcare",    "theme": "Defensive",   "etf": "PHARMABEES.NS","etf_name": "Pharma BeES",   "rank": 5, "signal": "HOLD",       "total_score": 0.38, "momentum_score": 0.12, "technical_score": 0.16,  "cycle_score": 0.10,  "ret_4w": -0.8, "ret_12w": 2.1, "ret_26w": 4.2, "ret_4w_vs_nifty": -2.1, "ret_12w_vs_nifty": -3.7, "ret_26w_vs_nifty": -5.2, "rsi": 47, "adx": 15, "macd_hist": -0.01, "above_e10": False, "above_e26": True, "above_e52": True, "ema_aligned": False, "reasons": ["4W lags Nifty by -2.1%", "12W lags Nifty by -3.7%", "26W lags Nifty by -5.2%", "Typical weakness in expansion phase"], "data_error": False},
        {"id": "fmcg",   "name": "FMCG",                   "theme": "Defensive",   "etf": None, "etf_name": None,                      "rank": 6, "signal": "HOLD",       "total_score": 0.32, "momentum_score": 0.08, "technical_score": 0.115, "cycle_score": 0.125, "ret_4w": -1.5, "ret_12w": 1.5, "ret_26w": 3.1, "ret_4w_vs_nifty": -3.1, "ret_12w_vs_nifty": -4.3, "ret_26w_vs_nifty": -6.3, "rsi": 44, "adx": 14, "macd_hist": -0.02, "above_e10": False, "above_e26": False, "above_e52": True, "ema_aligned": False, "reasons": ["4W lags Nifty by -3.1%", "Typically weak in expansion phase", "Below EMA26"], "data_error": False},
    ],
    "scan_time": "08 Jun 2026 15:45 IST",
    "elapsed_s": 12.4,
    "top_picks": ["Banking & Finance", "Nifty Midcap 100", "Information Technology"],
}


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/analysis")
async def get_sector_analysis(force: bool = False):
    """Run sector rotation analysis. Cached for 4 hours. Pass ?force=true to refresh."""
    if DEMO_MODE:
        return _DEMO_RESULT

    from backend.services.sector_analysis_service import (
        run_sector_analysis, get_cached_analysis, invalidate_cache
    )

    if force:
        invalidate_cache()

    cached = get_cached_analysis()
    if cached:
        return cached

    try:
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_sector_analysis)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Sector analysis failed: {exc}")


@router.post("/refresh")
async def refresh_sector_analysis():
    """Force a fresh sector scan (clears cache)."""
    if DEMO_MODE:
        return {"started": True, "message": "Demo mode — returning cached demo data."}
    from backend.services.sector_analysis_service import invalidate_cache
    invalidate_cache()
    return {"started": True, "message": "Cache cleared. Next /api/sectors/analysis call will re-scan."}


@router.get("/cycle")
async def get_market_cycle():
    """Return just the current market cycle phase — fast, uses cached data if available."""
    if DEMO_MODE:
        return _DEMO_RESULT["cycle"]

    from backend.services.sector_analysis_service import get_cached_analysis, run_sector_analysis
    cached = get_cached_analysis()
    if cached:
        return cached["cycle"]

    try:
        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_sector_analysis)
        return result["cycle"]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cycle detection failed: {exc}")
