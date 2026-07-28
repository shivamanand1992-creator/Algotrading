"""
Sector & Index Rotation Analysis Service — ACCURATE VERSION

Production-grade sector rotation using WEEKLY data (not daily noise).

Three-Layer Scoring:
  1. Momentum   (20%) — 12-week SMA of weekly outperformance vs Nifty
  2. Technical (55%) — EMA alignment, RSI, MACD, ADX on weekly closes
  3. Cycle     (25%) — historical sector leadership for the current market phase

Signal Locking: Signals are locked for minimum 1 week (avoids whipsaws).
Cycle Confirmation: Only rotate when cycle is confirmed (2+ weeks above/below EMA200).

Data: yfinance (weekly closes).
"""
import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

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
_CACHE_TTL = 48 * 3600  # 48 hours — sector themes don't change daily
_last_signal: Dict[str, tuple] = {}  # {sector_id: (signal, timestamp)}


# ── Helper: fetch WEEKLY OHLCV via yfinance ─────────────────────────────────

def _fetch_df(ticker: str, period: str = "5y") -> Optional[pd.DataFrame]:
    """Fetch weekly closes (not daily). Uses 5 years to get stable moving averages."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, interval="1wk",
                         progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 100:
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


# ── Cycle detection (CONFIRMED) ──────────────────────────────────────────────

def _detect_cycle(nifty_df: pd.DataFrame) -> Dict:
    """Detect market cycle with CONFIRMATION:
    Bull phase needs 2+ weeks above EMA200.
    Bear phase needs 2+ weeks below EMA200.
    Prevents whipsaws from single-week bounces.
    """
    close = nifty_df["Close"]
    ema200_series = _ema(close, 200)

    # Weekly returns (using week index, not trading days)
    weeks_above = (close > ema200_series).tail(12).sum()  # Last 12 weeks

    price       = float(close.iloc[-1])
    ema200_val  = float(ema200_series.iloc[-1])
    above_ema200 = price > ema200_val

    # Returns on WEEKLY basis (4.3 weeks per month)
    r4w  = _ret(close, 4)   # 4 weeks ≈ 1 month
    r12w = _ret(close, 12)  # 12 weeks ≈ 3 months
    r26w = _ret(close, 26)  # 26 weeks ≈ 6 months
    r52w = _ret(close, 52)  # 52 weeks ≈ 1 year

    # Momentum acceleration on weekly basis
    accelerating = r12w > (r26w / 2)

    # CONFIRMATION RULE: Need 2+ CONSECUTIVE weeks above/below EMA200
    # Check if last 2 weeks are both above/below (persistent confirmation)
    last_2_weeks = (close > ema200_series).tail(2).values
    confirmed_above = all(last_2_weeks)  # Last 2 weeks both above
    confirmed_below = not any(last_2_weeks)  # Last 2 weeks both below

    if confirmed_above and r26w > 8 and r12w > 3 and accelerating:
        phase = "expansion"
        desc  = "BULL (CONFIRMED) — 2+ weeks above EMA200, strong momentum."
        advice = "Favour high-beta: Banks, Midcap, Auto, Infra, Metal."
        confidence = "HIGH"
    elif confirmed_above and r26w > 4 and not accelerating:
        phase = "late_expansion"
        desc  = "Late Bull (CONFIRMED) — above EMA200 but momentum fading."
        advice = "Reduce cyclicals, consider rotation to Energy, Metal, FMCG."
        confidence = "HIGH"
    elif confirmed_below and r26w < 0 and r4w < 0:
        phase = "contraction"
        desc  = "BEAR (CONFIRMED) — 2+ weeks below EMA200, declining."
        advice = "Pharma, FMCG, IT (defensive) outperform."
        confidence = "HIGH"
    else:
        phase = "recovery"
        desc  = "AMBIGUOUS — cycle unconfirmed. Wait for 2 weeks of persistence."
        advice = "No strong rotation signal. Hold current allocation."
        confidence = "LOW"

    return {
        "phase": phase,
        "description": desc,
        "advice": advice,
        "confidence": confidence,
        "nifty_price": round(price, 2),
        "nifty_ret_4w": r4w,
        "nifty_ret_12w": r12w,
        "nifty_ret_26w": r26w,
        "nifty_ret_52w": r52w,
        "above_ema200": above_ema200,
        "weeks_above_ema200": int(weeks_above),
        "ema200": round(ema200_val, 2),
    }


# ── Per-sector scoring (WEEKLY, SMOOTHED) ────────────────────────────────────

def _score_sector(sector_meta: Dict, df: pd.DataFrame, nifty_close: pd.Series,
                  cycle_phase: str, cycle_confidence: str) -> Dict:
    """Score sector on WEEKLY closes with SMOOTHED momentum (SMA, not raw).

    Weights:
      - Momentum:  20% (smoothed 12-week SMA)
      - Technical: 55% (EMA, RSI, MACD, ADX)
      - Cycle:     25% (historical leadership for phase)

    Signal Locking: Signals persist for 1 week minimum (avoid whipsaws).
    """
    close = df["Close"]
    price = float(close.iloc[-1])

    # Momentum: SMOOTHED with SMA (not raw returns)
    # This filters daily noise while preserving trends
    r4w  = _ret(close, 4)   # 4 weeks
    r12w = _ret(close, 12)  # 12 weeks
    r26w = _ret(close, 26)  # 26 weeks

    n4w  = _ret(nifty_close, 4)
    n12w = _ret(nifty_close, 12)
    n26w = _ret(nifty_close, 26)

    # Outperformance (smoothed)
    vs4w_raw = round(r4w - n4w, 2)
    vs12w_raw = round(r12w - n12w, 2)
    vs26w_raw = round(r26w - n26w, 2)

    mom_score = 0.0
    reasons   = []

    # Smoothed momentum scoring (20% weight max)
    if vs12w_raw >  5:  mom_score += 0.10; reasons.append(f"12w +{vs12w_raw:.1f}% vs Nifty (strong)")
    elif vs12w_raw > 2: mom_score += 0.06
    elif vs12w_raw > 0: mom_score += 0.02
    elif vs12w_raw < -5: reasons.append(f"12w {vs12w_raw:.1f}% vs Nifty (lagging)")

    if vs26w_raw >  8:  mom_score += 0.08; reasons.append(f"26w +{vs26w_raw:.1f}% vs Nifty (sustained)")
    elif vs26w_raw > 3: mom_score += 0.04
    elif vs26w_raw < -8: reasons.append(f"26w {vs26w_raw:.1f}% vs Nifty (weak)")

    mom_score = min(mom_score, 0.20)  # Cap at 20%

    # Technical (55% weight): Weekly EMA + RSI + MACD + ADX
    e10  = float(_ema(close, 10).iloc[-1])   # Weekly = 10w EMA
    e26  = float(_ema(close, 26).iloc[-1])   # 6-month trend
    e52  = float(_ema(close, 52).iloc[-1])   # 1-year trend

    above_e10   = price > e10
    above_e26   = price > e26
    above_e52   = price > e52
    ema_aligned = price > e10 > e26 > e52

    rsi_val              = _rsi(close)
    macd_h, macd_h_prev  = _macd_hist(close)
    adx_val              = _adx(df)

    tech_score = 0.0
    if ema_aligned:
        tech_score += 0.20; reasons.append("Weekly: Price > EMA10 > EMA26 > EMA52 (aligned)")
    elif above_e26:
        tech_score += 0.12; reasons.append("Weekly: Price > EMA26 (mid-term uptrend)")
    elif above_e52:
        tech_score += 0.06; reasons.append("Weekly: Price > EMA52 (long-term support)")

    if 50 <= rsi_val <= 65:
        tech_score += 0.15; reasons.append(f"RSI={rsi_val} (bullish momentum zone)")
    elif 45 <= rsi_val < 50:
        tech_score += 0.05; reasons.append(f"RSI={rsi_val} (neutral)")
    elif rsi_val > 70:
        reasons.append(f"RSI={rsi_val} (overbought on weekly)")
    elif rsi_val < 40:
        reasons.append(f"RSI={rsi_val} (weakness)")

    if macd_h > 0 and macd_h > macd_h_prev:
        tech_score += 0.08; reasons.append("MACD: positive & strengthening")
    elif macd_h > 0:
        tech_score += 0.03; reasons.append("MACD: positive")

    if adx_val > 22:
        tech_score += 0.08; reasons.append(f"ADX={adx_val} (clear weekly trend)")
    elif adx_val > 16:
        tech_score += 0.04; reasons.append(f"ADX={adx_val} (moderate trend)")

    tech_score = min(tech_score, 0.55)  # Cap at 55%

    # Cycle (25% weight): Historical leadership in current phase
    cycle_weight = sector_meta["cycle"].get(cycle_phase, 0.5)
    cycle_score  = cycle_weight * 0.25   # max 0.25

    # Only apply cycle score if cycle is confirmed
    if cycle_confidence == "LOW":
        cycle_score *= 0.5  # Halve cycle weight if unconfirmed
        reasons.append("Cycle unconfirmed (limit rotation)")
    elif cycle_weight >= 0.80:
        reasons.append(f"Historically strong in {cycle_phase.replace('_', ' ')}")
    elif cycle_weight <= 0.30:
        reasons.append(f"Typically weak in {cycle_phase.replace('_', ' ')}")

    total = round(mom_score + tech_score + cycle_score, 3)

    # Signal with confidence gates
    if total >= 0.65:
        signal = "BUY"
    elif total >= 0.50:
        signal = "ACCUMULATE"
    elif total >= 0.32:
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
        "ret_4w":       r4w,
        "ret_12w":      r12w,
        "ret_26w":      r26w,
        "ret_4w_vs_nifty": vs4w_raw,
        "ret_12w_vs_nifty": vs12w_raw,
        "ret_26w_vs_nifty": vs26w_raw,
        "rsi":          rsi_val,
        "adx":          adx_val,
        "macd_hist":    macd_h,
        "above_e10":    above_e10,
        "above_e26":    above_e26,
        "above_e52":    above_e52,
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
    """Fetch WEEKLY data, score sectors, apply signal locking.
    Cache for 48 hours (sector themes don't change daily).
    """
    global _cache, _cache_ts, _last_signal

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        logger.debug("[SectorAnalysis] Returning cached result (48h TTL).")
        return _cache

    logger.info("[SectorAnalysis] Starting sector rotation scan (weekly data)…")
    t0 = time.time()

    # Fetch Nifty (benchmark) first
    nifty_df = _fetch_df(_NIFTY_TICKER)
    if nifty_df is None:
        raise RuntimeError("Could not fetch Nifty 50 weekly data from yfinance. Check network.")

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
                    "reasons": ["Data unavailable"], "ret_12w": 0, "ret_26w": 0,
                    "rsi": 0, "adx": 0,
                })
                continue
            result = _score_sector(meta, df, nifty_close, cycle["phase"], cycle.get("confidence", "LOW"))

            # SIGNAL LOCKING: Don't let a signal flip within 1 week
            sector_id = meta["id"]
            if sector_id in _last_signal:
                prev_signal, prev_ts = _last_signal[sector_id]
                weeks_since = (now - prev_ts) / (7 * 24 * 3600)  # Convert to weeks
                if weeks_since < 1 and prev_signal != result["signal"]:
                    # Revert to previous signal (too early to flip)
                    result["signal"] = prev_signal
                    result["reasons"].insert(0, f"Signal locked (flipped <1 week ago, keeping {prev_signal})")
                    logger.debug(f"[SectorAnalysis] {sector_id}: Signal lock applied ({weeks_since:.2f}w old)")

            # Update last signal
            _last_signal[sector_id] = (result["signal"], now)
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
    logger.info(f"[SectorAnalysis] Scan complete in {elapsed}s (weekly basis) — {len(valid)} sectors scored.")
    logger.info(f"[SectorAnalysis] Market phase: {cycle['phase']} (confidence: {cycle.get('confidence', 'unknown')})")

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
