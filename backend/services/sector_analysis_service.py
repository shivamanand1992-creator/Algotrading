"""
Sector & Index Rotation Analysis Service.

Combines three scoring layers:
  1. Momentum  (40%) — relative strength vs Nifty over 1M / 3M / 6M
  2. Technical (35%) — EMA trend, RSI, MACD, ADX
  3. Cycle     (25%) — historical sector leadership for the current market phase

Outputs a ranked list with BUY / ACCUMULATE / HOLD / AVOID signals.
Data source: yfinance (free, works without Angel One).
"""
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

import numpy as np
import pandas as pd
from loguru import logger

_IST = timezone(timedelta(hours=5, minutes=30))

# ── Sector universe ──────────────────────────────────────────────────────────

SECTOR_UNIVERSE = [
    {
        "id": "bank",    "name": "Banking & Finance",
        "index": "^NSEBANK",    "etf": "BANKBEES.NS",   "etf_name": "Bank BeES (Nippon)",
        "theme": "Financials",
        "cycle": {"recovery": 0.80, "expansion": 0.90, "late_expansion": 0.50, "contraction": 0.30},
    },
    {
        "id": "it",      "name": "Information Technology",
        "index": "^CNXIT",      "etf": "ITBEES.NS",     "etf_name": "Nifty IT ETF (Nippon)",
        "theme": "Technology",
        "cycle": {"recovery": 0.70, "expansion": 0.75, "late_expansion": 0.60, "contraction": 0.65},
    },
    {
        "id": "pharma",  "name": "Pharma & Healthcare",
        "index": "^CNXPHARMA",  "etf": "PHARMABEES.NS", "etf_name": "Pharma BeES (Nippon)",
        "theme": "Defensive",
        "cycle": {"recovery": 0.50, "expansion": 0.40, "late_expansion": 0.65, "contraction": 0.90},
    },
    {
        "id": "auto",    "name": "Automobiles",
        "index": "^CNXAUTO",    "etf": None,            "etf_name": None,
        "theme": "Consumer Discretionary",
        "cycle": {"recovery": 0.70, "expansion": 0.85, "late_expansion": 0.60, "contraction": 0.20},
    },
    {
        "id": "fmcg",    "name": "FMCG",
        "index": "^CNXFMCG",    "etf": None,            "etf_name": None,
        "theme": "Defensive",
        "cycle": {"recovery": 0.40, "expansion": 0.50, "late_expansion": 0.70, "contraction": 0.80},
    },
    {
        "id": "metal",   "name": "Metals & Mining",
        "index": "^CNXMETAL",   "etf": None,            "etf_name": None,
        "theme": "Cyclical",
        "cycle": {"recovery": 0.60, "expansion": 0.80, "late_expansion": 0.90, "contraction": 0.15},
    },
    {
        "id": "realty",  "name": "Real Estate",
        "index": "^CNXREALTY",  "etf": None,            "etf_name": None,
        "theme": "Cyclical",
        "cycle": {"recovery": 0.90, "expansion": 0.80, "late_expansion": 0.40, "contraction": 0.10},
    },
    {
        "id": "energy",  "name": "Energy & Oil",
        "index": "^CNXENERGY",  "etf": None,            "etf_name": None,
        "theme": "Energy",
        "cycle": {"recovery": 0.50, "expansion": 0.70, "late_expansion": 0.90, "contraction": 0.25},
    },
    {
        "id": "infra",   "name": "Infrastructure",
        "index": "^CNXINFRA",   "etf": None,            "etf_name": None,
        "theme": "Cyclical",
        "cycle": {"recovery": 0.70, "expansion": 0.85, "late_expansion": 0.70, "contraction": 0.15},
    },
    {
        "id": "midcap",  "name": "Nifty Midcap 100",
        "index": "^NSMIDCP100", "etf": "JUNIORBEES.NS", "etf_name": "Junior BeES (Next50)",
        "theme": "Broad Market",
        "cycle": {"recovery": 0.80, "expansion": 0.90, "late_expansion": 0.55, "contraction": 0.15},
    },
    {
        "id": "nifty50", "name": "Nifty 50 (Benchmark)",
        "index": "^NSEI",       "etf": "NIFTYBEES.NS",  "etf_name": "Nifty BeES (Nippon)",
        "theme": "Broad Market",
        "cycle": {"recovery": 0.70, "expansion": 0.80, "late_expansion": 0.60, "contraction": 0.30},
    },
]

_NIFTY_TICKER = "^NSEI"

# ── Cache ────────────────────────────────────────────────────────────────────

_cache: Optional[Dict] = None
_cache_ts: float = 0.0
_CACHE_TTL = 4 * 3600  # 4 hours


# ── Helper: fetch OHLCV via yfinance ─────────────────────────────────────────

def _fetch_df(ticker: str, period: str = "400d") -> Optional[pd.DataFrame]:
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 60:
            return None
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        return df
    except Exception as exc:
        logger.warning(f"[SectorAnalysis] yfinance fetch failed for {ticker}: {exc}")
        return None


# ── Technical indicators (manual, no pandas_ta) ──────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    ag = gain.ewm(alpha=1 / period, adjust=False).mean()
    al = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = ag / al.replace(0, np.inf)
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)


def _macd_hist(close: pd.Series) -> tuple:
    e12   = _ema(close, 12)
    e26   = _ema(close, 26)
    macd  = e12 - e26
    sig   = _ema(macd, 9)
    hist  = macd - sig
    return round(float(hist.iloc[-1]), 4), round(float(hist.iloc[-2]) if len(hist) > 1 else 0, 4)


def _adx(df: pd.DataFrame, period: int = 14) -> float:
    try:
        high  = df["High"]  if "High"  in df.columns else df["Close"]
        low   = df["Low"]   if "Low"   in df.columns else df["Close"]
        close = df["Close"]
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low  - close.shift(1)).abs()
        tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        dm_p = high.diff().clip(lower=0)
        dm_n = (-low.diff()).clip(lower=0)
        dm_p = dm_p.where(dm_p > dm_n, 0)
        dm_n = dm_n.where(dm_n > dm_p, 0)
        di_p = 100 * dm_p.ewm(span=period, adjust=False).mean() / atr
        di_n = 100 * dm_n.ewm(span=period, adjust=False).mean() / atr
        denom = (di_p + di_n).replace(0, 1)
        dx    = 100 * (di_p - di_n).abs() / denom
        adx   = dx.ewm(span=period, adjust=False).mean()
        return round(float(adx.iloc[-1]), 1)
    except Exception:
        return 20.0


def _ret(close: pd.Series, trading_days: int) -> float:
    if len(close) < trading_days + 1:
        return 0.0
    return round((close.iloc[-1] / close.iloc[-trading_days] - 1) * 100, 2)


# ── Cycle detection ──────────────────────────────────────────────────────────

def _detect_cycle(nifty_df: pd.DataFrame) -> Dict:
    close = nifty_df["Close"]
    r1m  = _ret(close, 22)
    r3m  = _ret(close, 66)
    r6m  = _ret(close, 132)
    r12m = _ret(close, 252)

    ema200_val  = float(_ema(close, 200).iloc[-1])
    price       = float(close.iloc[-1])
    above_ema200 = price > ema200_val

    # Momentum acceleration: 3M run rate vs 6M run rate
    accelerating = r3m > (r6m / 2)

    if above_ema200 and r6m > 8 and r3m > 3 and accelerating:
        phase = "expansion"
        desc  = "Bull market expansion — cyclicals, banks, mid-caps historically lead."
        advice = "Favour high-beta sectors: Banks, Midcap, Auto, Infra, Metal."
    elif above_ema200 and r6m > 4 and not accelerating:
        phase = "late_expansion"
        desc  = "Late expansion / topping out — momentum slowing, selectivity needed."
        advice = "Rotate toward Energy, Metal, FMCG. Reduce high-beta exposure."
    elif not above_ema200 and r6m < 0 and r1m < 0:
        phase = "contraction"
        desc  = "Bear market / correction — defensive sectors preserve capital."
        advice = "Pharma, FMCG, IT (for earnings visibility) outperform historically."
    else:
        phase = "recovery"
        desc  = "Recovery / early bull — financials, real estate, consumer discretionary lead."
        advice = "Banks, Realty, Auto and IT typically outperform in early recovery."

    return {
        "phase": phase,
        "description": desc,
        "advice": advice,
        "nifty_price": round(price, 2),
        "nifty_ret_1m": r1m,
        "nifty_ret_3m": r3m,
        "nifty_ret_6m": r6m,
        "nifty_ret_12m": r12m,
        "above_ema200": above_ema200,
        "ema200": round(ema200_val, 2),
    }


# ── Per-sector scoring ───────────────────────────────────────────────────────

def _score_sector(sector_meta: Dict, df: pd.DataFrame, nifty_close: pd.Series,
                  cycle_phase: str) -> Dict:
    close = df["Close"]
    price = float(close.iloc[-1])

    # Momentum
    r1m  = _ret(close, 22)
    r3m  = _ret(close, 66)
    r6m  = _ret(close, 132)
    n1m  = _ret(nifty_close, 22)
    n3m  = _ret(nifty_close, 66)
    n6m  = _ret(nifty_close, 132)
    vs1m = round(r1m - n1m, 2)
    vs3m = round(r3m - n3m, 2)
    vs6m = round(r6m - n6m, 2)

    mom_score = 0.0
    reasons   = []
    if vs1m >  3:  mom_score += 0.15; reasons.append(f"1M outperforms Nifty by +{vs1m:.1f}%")
    elif vs1m > 1: mom_score += 0.08
    elif vs1m < -3: reasons.append(f"1M lags Nifty by {vs1m:.1f}%")

    if vs3m >  5:  mom_score += 0.15; reasons.append(f"3M outperforms Nifty by +{vs3m:.1f}%")
    elif vs3m > 2: mom_score += 0.08
    elif vs3m < -5: reasons.append(f"3M lags Nifty by {vs3m:.1f}%")

    if vs6m >  8:  mom_score += 0.10; reasons.append(f"6M outperforms Nifty by +{vs6m:.1f}%")
    elif vs6m > 3: mom_score += 0.05
    elif vs6m < -8: reasons.append(f"6M lags Nifty by {vs6m:.1f}%")

    mom_score = min(mom_score, 0.40)

    # Technical
    e20  = float(_ema(close, 20).iloc[-1])
    e50  = float(_ema(close, 50).iloc[-1])
    e200 = float(_ema(close, 200).iloc[-1])
    above_ema20  = price > e20
    above_ema50  = price > e50
    above_ema200 = price > e200
    ema_aligned  = price > e20 > e50 > e200

    rsi_val              = _rsi(close)
    macd_h, macd_h_prev  = _macd_hist(close)
    adx_val              = _adx(df)

    tech_score = 0.0
    if ema_aligned:
        tech_score += 0.15; reasons.append("Price > EMA20 > EMA50 > EMA200 (fully aligned)")
    elif above_ema50:
        tech_score += 0.08; reasons.append("Price above EMA50")
    elif above_ema200:
        tech_score += 0.04

    if 50 <= rsi_val <= 70:
        tech_score += 0.10; reasons.append(f"RSI={rsi_val} (momentum zone)")
    elif 45 <= rsi_val < 50:
        tech_score += 0.05
    elif rsi_val > 75:
        reasons.append(f"RSI={rsi_val} (overbought — caution)")
    elif rsi_val < 40:
        reasons.append(f"RSI={rsi_val} (weak momentum)")

    if macd_h > 0 and macd_h > macd_h_prev:
        tech_score += 0.05; reasons.append("MACD histogram positive & rising")
    elif macd_h > 0:
        tech_score += 0.02

    if adx_val > 25:
        tech_score += 0.05; reasons.append(f"ADX={adx_val} (strong trend)")
    elif adx_val > 18:
        tech_score += 0.02

    tech_score = min(tech_score, 0.35)

    # Cycle
    cycle_weight = sector_meta["cycle"].get(cycle_phase, 0.5)
    cycle_score  = cycle_weight * 0.25   # max 0.25

    if cycle_weight >= 0.80:
        reasons.append(f"Historically strong in {cycle_phase.replace('_', ' ')} phase")
    elif cycle_weight <= 0.30:
        reasons.append(f"Typically weak in {cycle_phase.replace('_', ' ')} phase")

    total = round(mom_score + tech_score + cycle_score, 3)

    # Signal
    if total >= 0.62:
        signal = "BUY"
    elif total >= 0.45:
        signal = "ACCUMULATE"
    elif total >= 0.28:
        signal = "HOLD"
    else:
        signal = "AVOID"

    return {
        "id":           sector_meta["id"],
        "name":         sector_meta["name"],
        "theme":        sector_meta["theme"],
        "etf":          sector_meta["etf"],
        "etf_name":     sector_meta["etf_name"],
        "price":        round(price, 2),
        "ret_1m":       r1m,
        "ret_3m":       r3m,
        "ret_6m":       r6m,
        "ret_1m_vs_nifty": vs1m,
        "ret_3m_vs_nifty": vs3m,
        "ret_6m_vs_nifty": vs6m,
        "rsi":          rsi_val,
        "adx":          adx_val,
        "macd_hist":    macd_h,
        "above_ema20":  above_ema20,
        "above_ema50":  above_ema50,
        "above_ema200": above_ema200,
        "ema_aligned":  ema_aligned,
        "momentum_score": round(mom_score, 3),
        "technical_score": round(tech_score, 3),
        "cycle_score":  round(cycle_score, 3),
        "total_score":  total,
        "signal":       signal,
        "reasons":      reasons,
        "data_error":   False,
    }


# ── Public API ───────────────────────────────────────────────────────────────

def run_sector_analysis() -> Dict:
    """Fetch data for all sectors, score, and rank. Returns full analysis dict.
    This is synchronous — call via run_in_executor from async context.
    Cache result for 4 hours.
    """
    global _cache, _cache_ts

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        logger.debug("[SectorAnalysis] Returning cached result.")
        return _cache

    logger.info("[SectorAnalysis] Starting sector rotation scan…")
    t0 = time.time()

    # Fetch Nifty (benchmark) first
    nifty_df = _fetch_df(_NIFTY_TICKER)
    if nifty_df is None:
        raise RuntimeError("Could not fetch Nifty 50 data from yfinance. Check network.")

    cycle = _detect_cycle(nifty_df)
    nifty_close = nifty_df["Close"]

    # Score each sector
    scored = []
    for meta in SECTOR_UNIVERSE:
        try:
            df = _fetch_df(meta["index"])
            if df is None:
                logger.warning(f"[SectorAnalysis] No data for {meta['id']} ({meta['index']}) — skipping.")
                scored.append({
                    **{k: meta[k] for k in ("id", "name", "theme", "etf", "etf_name")},
                    "data_error": True, "signal": "N/A", "total_score": 0.0,
                    "reasons": ["Data unavailable"], "ret_1m": 0, "ret_3m": 0,
                    "ret_6m": 0, "rsi": 0, "adx": 0,
                })
                continue
            result = _score_sector(meta, df, nifty_close, cycle["phase"])
            scored.append(result)
        except Exception as exc:
            logger.error(f"[SectorAnalysis] Error scoring {meta['id']}: {exc}")
            scored.append({
                **{k: meta[k] for k in ("id", "name", "theme", "etf", "etf_name")},
                "data_error": True, "signal": "N/A", "total_score": 0.0,
                "reasons": [f"Error: {exc}"],
            })

    # Rank by total_score (exclude errored entries)
    valid   = [s for s in scored if not s.get("data_error")]
    errored = [s for s in scored if s.get("data_error")]
    valid.sort(key=lambda x: x["total_score"], reverse=True)
    for i, s in enumerate(valid, 1):
        s["rank"] = i
    for s in errored:
        s["rank"] = 99

    elapsed = round(time.time() - t0, 1)
    scan_time = datetime.now(_IST).strftime("%d %b %Y %H:%M IST")
    logger.info(f"[SectorAnalysis] Scan complete in {elapsed}s — {len(valid)} sectors scored.")

    result = {
        "cycle":     cycle,
        "sectors":   valid + errored,
        "scan_time": scan_time,
        "elapsed_s": elapsed,
        "top_picks": [s["name"] for s in valid[:3] if s["signal"] in ("BUY", "ACCUMULATE")],
    }

    _cache    = result
    _cache_ts = now
    return result


def get_cached_analysis() -> Optional[Dict]:
    """Return cached result if still fresh, else None."""
    if _cache and (time.time() - _cache_ts) < _CACHE_TTL:
        return _cache
    return None


def invalidate_cache() -> None:
    global _cache, _cache_ts
    _cache    = None
    _cache_ts = 0.0
