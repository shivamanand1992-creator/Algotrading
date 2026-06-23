"""
Portfolio Analysis Service
==========================
For each holding symbol computes:
  - Technical analysis  (RSI, MACD, Bollinger Bands, moving averages via ta + yfinance)
  - Fundamental analysis (P/E, P/B, ROE, growth metrics via yfinance)
  - AI recommendation from Claude Haiku (Hold / Add More / Sell) + score 1-10
Results are cached for 1 hour to avoid hammering the Claude API.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pytz
from loguru import logger

sys.path.append(str(Path(__file__).parent.parent.parent))

_IST            = pytz.timezone("Asia/Kolkata")
_CACHE_TTL_S    = 3600  # 1 hour
_CACHE: Dict[str, Dict[str, Any]] = {}


def _cache_get(symbol: str) -> Optional[Dict[str, Any]]:
    entry = _CACHE.get(symbol)
    if not entry:
        return None
    age = (datetime.now(_IST) - entry["ts"]).total_seconds()
    if age > _CACHE_TTL_S:
        _CACHE.pop(symbol, None)
        return None
    return entry["data"]


def _cache_set(symbol: str, data: Dict[str, Any]) -> None:
    _CACHE[symbol] = {"data": data, "ts": datetime.now(_IST)}


# ---------------------------------------------------------------------------
# Technical Analysis
# ---------------------------------------------------------------------------

def _compute_ta(symbol: str) -> Dict[str, Any]:
    try:
        import yfinance as yf
        import ta as ta_lib

        df = yf.download(f"{symbol}.NS", period="6mo", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty or len(df) < 30:
            return {"error": "Insufficient price data"}

        close  = df["Close"].squeeze()
        high   = df["High"].squeeze()
        low    = df["Low"].squeeze()
        volume = df["Volume"].squeeze()

        # RSI
        rsi     = float(ta_lib.momentum.RSIIndicator(close, window=14).rsi().iloc[-1])
        rsi_sig = "Oversold" if rsi < 30 else "Overbought" if rsi > 70 else "Neutral"

        # MACD
        macd_obj  = ta_lib.trend.MACD(close)
        macd_val  = float(macd_obj.macd().iloc[-1])
        macd_sig  = float(macd_obj.macd_signal().iloc[-1])
        macd_hist = float(macd_obj.macd_diff().iloc[-1])

        # Bollinger Bands
        bb      = ta_lib.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_up   = float(bb.bollinger_hband().iloc[-1])
        bb_lo   = float(bb.bollinger_lband().iloc[-1])
        bb_mid  = float(bb.bollinger_mavg().iloc[-1])

        cur = float(close.iloc[-1])
        bb_pos = ("Above upper" if cur > bb_up
                  else "Below lower" if cur < bb_lo
                  else "Inside bands")

        # Moving averages
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        ema20 = float(close.ewm(span=20).mean().iloc[-1])

        # 52-week extremes
        w52   = min(len(high), 252)
        h52   = float(high.iloc[-w52:].max())
        l52   = float(low.iloc[-w52:].min())
        pct_h = round(((cur - h52) / h52) * 100, 1) if h52 else 0.0

        return {
            "current_price":      round(cur, 2),
            "rsi":                round(rsi, 1),
            "rsi_signal":         rsi_sig,
            "macd":               round(macd_val, 2),
            "macd_signal":        round(macd_sig, 2),
            "macd_histogram":     round(macd_hist, 2),
            "macd_bullish":       macd_hist > 0,
            "bb_upper":           round(bb_up, 2),
            "bb_lower":           round(bb_lo, 2),
            "bb_mid":             round(bb_mid, 2),
            "price_vs_bb":        bb_pos,
            "sma_20":             round(sma20, 2),
            "sma_50":             round(sma50, 2) if sma50 else None,
            "ema_20":             round(ema20, 2),
            "above_sma20":        cur > sma20,
            "above_sma50":        (cur > sma50) if sma50 else None,
            "high_52w":           round(h52, 2),
            "low_52w":            round(l52, 2),
            "pct_from_52w_high":  pct_h,
            "avg_volume_20d":     int(volume.rolling(20).mean().iloc[-1]),
            "last_volume":        int(volume.iloc[-1]),
        }
    except Exception as exc:
        logger.warning(f"[Analysis] TA failed for {symbol}: {exc}")
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Fundamental Analysis
# ---------------------------------------------------------------------------

def _compute_fa(symbol: str) -> Dict[str, Any]:
    try:
        import yfinance as yf

        info = yf.Ticker(f"{symbol}.NS").info

        def _s(key, default=None):
            v = info.get(key)
            return v if v not in (None, "N/A", "", 0) else default

        mc = _s("marketCap")

        def _fmt_cap(v):
            if not v:
                return None
            if v >= 1e12:
                return f"₹{v/1e12:.1f}T"
            if v >= 1e9:
                return f"₹{v/1e9:.1f}B"
            return f"₹{v/1e7:.0f}Cr"

        def _pct(key):
            v = _s(key)
            return round(float(v) * 100, 1) if v is not None else None

        def _f(key, dec=2):
            v = _s(key)
            return round(float(v), dec) if v is not None else None

        return {
            "market_cap_fmt":      _fmt_cap(mc),
            "trailing_pe":         _f("trailingPE", 1),
            "forward_pe":          _f("forwardPE", 1),
            "price_to_book":       _f("priceToBook"),
            "dividend_yield_pct":  _pct("dividendYield"),
            "roe_pct":             _pct("returnOnEquity"),
            "revenue_growth_pct":  _pct("revenueGrowth"),
            "earnings_growth_pct": _pct("earningsGrowth"),
            "debt_to_equity":      _f("debtToEquity"),
            "current_ratio":       _f("currentRatio"),
            "profit_margin_pct":   _pct("profitMargins"),
            "sector":              _s("sector"),
            "industry":            _s("industry"),
            "full_name":           _s("longName") or symbol,
        }
    except Exception as exc:
        logger.warning(f"[Analysis] FA failed for {symbol}: {exc}")
        return {"error": str(exc), "full_name": symbol}


# ---------------------------------------------------------------------------
# AI Recommendation
# ---------------------------------------------------------------------------

def _ai_recommend(symbol: str, ta: Dict, fa: Dict, holding: Dict) -> Dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "recommendation": "HOLD",
            "score": 5,
            "summary": "AI analysis unavailable — ANTHROPIC_API_KEY not set.",
            "technical_verdict": "N/A",
            "fundamental_verdict": "N/A",
            "key_risks": [],
            "key_positives": [],
        }

    try:
        import anthropic

        pnl_pct   = holding.get("pnl_pct", 0)
        qty       = holding.get("qty", 0)
        avg_price = holding.get("avg_price", 0)
        cur_price = holding.get("current_price", ta.get("current_price", avg_price))

        prompt = f"""You are a senior Indian equity analyst with 20+ years of experience. Analyse this holding and give a concise, actionable recommendation.

Stock: {symbol} ({fa.get('full_name', symbol)})
Sector: {fa.get('sector', 'N/A')} — {fa.get('industry', 'N/A')}
Current holding: {qty} shares at avg ₹{avg_price} | LTP ₹{cur_price} | P&L {'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%

TECHNICAL:
- RSI(14): {ta.get('rsi', 'N/A')} [{ta.get('rsi_signal', 'N/A')}]
- MACD histogram: {ta.get('macd_histogram', 'N/A')} [{'Bullish' if ta.get('macd_bullish') else 'Bearish'}]
- Bollinger Bands: {ta.get('price_vs_bb', 'N/A')}
- SMA20: ₹{ta.get('sma_20', 'N/A')} [{'Price above' if ta.get('above_sma20') else 'Price below'}]
- SMA50: ₹{ta.get('sma_50', 'N/A')}
- 52W Range: ₹{ta.get('low_52w', 'N/A')} – ₹{ta.get('high_52w', 'N/A')} [{ta.get('pct_from_52w_high', 'N/A')}% from high]

FUNDAMENTAL:
- Market Cap: {fa.get('market_cap_fmt', 'N/A')}
- P/E (TTM): {fa.get('trailing_pe', 'N/A')} | Forward P/E: {fa.get('forward_pe', 'N/A')}
- P/B: {fa.get('price_to_book', 'N/A')}
- ROE: {fa.get('roe_pct', 'N/A')}%
- Revenue Growth: {fa.get('revenue_growth_pct', 'N/A')}%
- Earnings Growth: {fa.get('earnings_growth_pct', 'N/A')}%
- Profit Margin: {fa.get('profit_margin_pct', 'N/A')}%
- Debt/Equity: {fa.get('debt_to_equity', 'N/A')}
- Dividend Yield: {fa.get('dividend_yield_pct', 'N/A')}%

Respond in this exact JSON format only:
{{
  "recommendation": "HOLD" | "ADD MORE" | "SELL",
  "score": <1–10 integer, 10 = strong buy>,
  "summary": "<2–3 sentence overview of the stock's current condition and investment case>",
  "technical_verdict": "<one sentence on technical setup>",
  "fundamental_verdict": "<one sentence on fundamental quality>",
  "key_risks": ["<risk 1>", "<risk 2>"],
  "key_positives": ["<positive 1>", "<positive 2>"]
}}"""

        client = anthropic.Anthropic(api_key=api_key)
        resp   = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text  = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        return json.loads(text)

    except Exception as exc:
        logger.warning(f"[Analysis] AI recommendation failed for {symbol}: {exc}")
        return {
            "recommendation": "HOLD",
            "score": 5,
            "summary": f"AI analysis temporarily unavailable: {str(exc)[:120]}",
            "technical_verdict": "N/A",
            "fundamental_verdict": "N/A",
            "key_risks": [],
            "key_positives": [],
        }


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

async def analyze_symbol(symbol: str, holding: Dict[str, Any]) -> Dict[str, Any]:
    """Full analysis: TA + FA + AI recommendation.  Cached for 1 hour."""
    cached = _cache_get(symbol)
    if cached:
        return cached

    loop = asyncio.get_event_loop()

    ta_data, fa_data = await asyncio.gather(
        loop.run_in_executor(None, _compute_ta, symbol),
        loop.run_in_executor(None, _compute_fa, symbol),
    )
    ai_data = await loop.run_in_executor(None, _ai_recommend, symbol, ta_data, fa_data, holding)

    result = {
        "symbol":      symbol,
        "technical":   ta_data,
        "fundamental": fa_data,
        "ai":          ai_data,
        "analyzed_at": datetime.now(_IST).strftime("%d %b %Y %H:%M IST"),
    }
    _cache_set(symbol, result)
    return result
