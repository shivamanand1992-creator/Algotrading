"""
Stock Conviction Service
========================
On-demand deep analysis for any NSE ticker:
  - TA + FA via yfinance (same approach as portfolio_analysis_service)
  - Full conviction JSON from Claude: Bull/Bear/Base thesis, red flags,
    green flags, catalysts, entry zones, peer tickers, price distribution
  - Peer metrics fetched from yfinance after Claude identifies them
  - Results cached 2 hours
"""
from __future__ import annotations

import asyncio
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz
from loguru import logger

_IST = pytz.timezone("Asia/Kolkata")
_CACHE_TTL_S = 7200  # 2 hours
_CACHE: Dict[str, Dict[str, Any]] = {}


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    entry = _CACHE.get(key)
    if not entry:
        return None
    if (datetime.now(_IST) - entry["ts"]).total_seconds() > _CACHE_TTL_S:
        _CACHE.pop(key, None)
        return None
    return entry["data"]


def _cache_set(key: str, data: Dict[str, Any]) -> None:
    _CACHE[key] = {"data": data, "ts": datetime.now(_IST)}


def _f(val, decimals: int = 2) -> Optional[float]:
    try:
        v = float(val)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, decimals)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Stock data fetch (TA + FA)
# ---------------------------------------------------------------------------

def _fetch_stock_data(symbol: str) -> Dict[str, Any]:
    try:
        import yfinance as yf
        import ta as ta_lib

        ticker_sym = f"{symbol}.NS"
        df = yf.download(ticker_sym, period="1y", interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 30:
            return {"error": f"No price data found for {symbol}"}

        close  = df["Close"].squeeze()
        high   = df["High"].squeeze()
        low    = df["Low"].squeeze()
        volume = df["Volume"].squeeze()
        cur    = _f(close.iloc[-1]) or 0.0

        # RSI
        rsi_raw = _f(ta_lib.momentum.RSIIndicator(close, window=14).rsi().iloc[-1], 1)
        rsi     = rsi_raw if rsi_raw is not None else 50.0

        # MACD
        macd_obj  = ta_lib.trend.MACD(close)
        macd_hist = _f(macd_obj.macd_diff().iloc[-1])

        # Bollinger Bands
        bb    = ta_lib.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_up = _f(bb.bollinger_hband().iloc[-1])
        bb_lo = _f(bb.bollinger_lband().iloc[-1])

        # Moving averages
        sma20 = _f(close.rolling(20).mean().iloc[-1])
        sma50 = _f(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None

        # 52-week
        w52 = min(len(high), 252)
        h52 = _f(high.iloc[-w52:].max())
        l52 = _f(low.iloc[-w52:].min())
        pct_h = round(((cur - h52) / h52) * 100, 1) if h52 else 0.0

        # Volume
        avg_vol  = _f(volume.rolling(20).mean().iloc[-1], 0)
        last_vol = _f(volume.iloc[-1], 0)

        # Fundamentals
        try:
            info = yf.Ticker(ticker_sym).info
        except Exception:
            info = {}

        def _s(key, default=None):
            v = info.get(key)
            if v in (None, "N/A", "", 0, "None"):
                return default
            try:
                fv = float(v)
                return default if (math.isnan(fv) or math.isinf(fv)) else v
            except (TypeError, ValueError):
                return v

        def _pct(key):
            v = _s(key)
            try:
                fv = float(v)
                return round(fv * 100, 1) if not math.isnan(fv) else None
            except Exception:
                return None

        def _fa_f(key, dec=2):
            v = _s(key)
            try:
                fv = float(v)
                return round(fv, dec) if not math.isnan(fv) else None
            except Exception:
                return None

        mc = _s("marketCap")

        def _fmt_cap(v):
            if not v:
                return None
            try:
                v = float(v)
                if v >= 1e12: return f"₹{v/1e12:.1f}T"
                if v >= 1e9:  return f"₹{v/1e9:.1f}B"
                return f"₹{v/1e7:.0f}Cr"
            except Exception:
                return None

        return {
            "symbol":           symbol,
            "full_name":        _s("longName") or symbol,
            "sector":           _s("sector"),
            "industry":         _s("industry"),
            "current_price":    cur,
            "market_cap_fmt":   _fmt_cap(mc),
            "rsi":              rsi,
            "rsi_signal":       "Oversold" if rsi < 30 else "Overbought" if rsi > 70 else "Neutral",
            "macd_bullish":     (macd_hist or 0) > 0,
            "bb_position":      ("Above upper" if (bb_up and cur > bb_up)
                                 else "Below lower" if (bb_lo and cur < bb_lo)
                                 else "Inside bands"),
            "sma_20":           sma20,
            "sma_50":           sma50,
            "above_sma20":      cur > (sma20 or 0),
            "above_sma50":      (cur > sma50) if sma50 else None,
            "high_52w":         h52,
            "low_52w":          l52,
            "pct_from_52w_high": pct_h,
            "avg_volume_20d":   int(avg_vol) if avg_vol else None,
            "last_volume":      int(last_vol) if last_vol else None,
            "trailing_pe":      _fa_f("trailingPE", 1),
            "forward_pe":       _fa_f("forwardPE", 1),
            "price_to_book":    _fa_f("priceToBook"),
            "roe_pct":          _pct("returnOnEquity"),
            "revenue_growth_pct": _pct("revenueGrowth"),
            "earnings_growth_pct": _pct("earningsGrowth"),
            "profit_margin_pct": _pct("profitMargins"),
            "debt_to_equity":   _fa_f("debtToEquity"),
            "current_ratio":    _fa_f("currentRatio"),
            "dividend_yield_pct": _pct("dividendYield"),
        }
    except Exception as exc:
        logger.warning(f"[Conviction] Data fetch failed for {symbol}: {exc}")
        return {"error": str(exc), "symbol": symbol}


# ---------------------------------------------------------------------------
# Peer data fetch
# ---------------------------------------------------------------------------

def _fetch_peer_data(peer_tickers: List[str]) -> List[Dict[str, Any]]:
    peers = []
    for ticker in peer_tickers[:6]:
        try:
            import yfinance as yf
            info = yf.Ticker(f"{ticker}.NS").info

            def _s(key, default=None):
                v = info.get(key)
                if v in (None, "N/A", "", 0, "None"):
                    return default
                try:
                    fv = float(v)
                    return default if (math.isnan(fv) or math.isinf(fv)) else v
                except (TypeError, ValueError):
                    return v

            def _fa_f(key, dec=1):
                v = _s(key)
                try:
                    fv = float(v)
                    return round(fv, dec) if not math.isnan(fv) else None
                except Exception:
                    return None

            def _pct(key):
                v = _s(key)
                try:
                    fv = float(v)
                    return round(fv * 100, 1) if not math.isnan(fv) else None
                except Exception:
                    return None

            peers.append({
                "ticker":        ticker,
                "name":          _s("longName") or ticker,
                "pe":            _fa_f("trailingPE"),
                "pb":            _fa_f("priceToBook"),
                "growth":        _pct("revenueGrowth"),
                "roe":           _pct("returnOnEquity"),
                "market_cap":    _f(_s("marketCap"), 0),
                "current_price": _f(_s("currentPrice") or _s("regularMarketPrice")),
            })
        except Exception as exc:
            logger.warning(f"[Conviction] Peer fetch failed for {ticker}: {exc}")
    return peers


# ---------------------------------------------------------------------------
# Claude conviction analysis
# ---------------------------------------------------------------------------

def _generate_conviction(symbol: str, sd: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set"}

    try:
        import anthropic

        prompt = f"""You are a senior Indian equity research analyst. Analyse this NSE stock and return a COMPREHENSIVE conviction JSON.

STOCK: {symbol} ({sd.get('full_name', symbol)})
Sector: {sd.get('sector', 'N/A')} — {sd.get('industry', 'N/A')}
Current Price: ₹{sd.get('current_price', 'N/A')}
Market Cap: {sd.get('market_cap_fmt', 'N/A')}

TECHNICAL:
- RSI(14): {sd.get('rsi', 'N/A')} [{sd.get('rsi_signal', 'N/A')}]
- MACD: {'Bullish' if sd.get('macd_bullish') else 'Bearish'}
- Bollinger Bands: {sd.get('bb_position', 'N/A')}
- SMA20: ₹{sd.get('sma_20', 'N/A')} [{'Above' if sd.get('above_sma20') else 'Below'}]
- SMA50: ₹{sd.get('sma_50', 'N/A')}
- 52W: ₹{sd.get('low_52w', 'N/A')} – ₹{sd.get('high_52w', 'N/A')} [{sd.get('pct_from_52w_high', 'N/A')}% from 52W high]

FUNDAMENTAL:
- P/E (TTM): {sd.get('trailing_pe', 'N/A')} | Forward P/E: {sd.get('forward_pe', 'N/A')}
- P/B: {sd.get('price_to_book', 'N/A')}
- ROE: {sd.get('roe_pct', 'N/A')}%
- Revenue Growth: {sd.get('revenue_growth_pct', 'N/A')}%
- Earnings Growth: {sd.get('earnings_growth_pct', 'N/A')}%
- Profit Margin: {sd.get('profit_margin_pct', 'N/A')}%
- Debt/Equity: {sd.get('debt_to_equity', 'N/A')}
- Current Ratio: {sd.get('current_ratio', 'N/A')}
- Dividend Yield: {sd.get('dividend_yield_pct', 'N/A')}%

Return ONLY valid JSON (no markdown) matching this EXACT schema:
{{
  "conviction": {{
    "score": <1-10 integer>,
    "action": "<BUY | ACCUMULATE | HOLD | WAIT | AVOID>",
    "action_detail": "<specific e.g. 'Wait for dip to ₹1,400–1,500'>",
    "why_matters": ["<reason, max 70 chars>", "<reason>", "<reason>"],
    "risk_reward": "<e.g. '2.1:1 downside risk'>",
    "estimated_fair_value": <number>,
    "upside_pct": <number, negative if overvalued>
  }},
  "thesis": {{
    "bull": {{
      "score": <number 1-10>,
      "probability": <integer 0-100>,
      "points": ["<point>", "<point>", "<point>"],
      "fair_value": <number>,
      "trigger": "<what must happen>"
    }},
    "bear": {{
      "score": <number 1-10>,
      "probability": <integer 0-100>,
      "points": ["<point>", "<point>", "<point>"],
      "fair_value": <number>,
      "trigger": "<what must happen>"
    }},
    "base": {{
      "score": <number 1-10>,
      "probability": <integer 0-100>,
      "points": ["<point>", "<point>", "<point>"],
      "fair_value": <number>,
      "trigger": "<most likely scenario>"
    }}
  }},
  "red_flags": [
    {{
      "name": "<flag name>",
      "detail": "<current vs historical metric or specific concern>",
      "severity": "<high|medium|low>",
      "action": "<what to monitor>"
    }}
  ],
  "green_flags": ["<positive 1>", "<positive 2>", "<positive 3>"],
  "catalysts": [
    {{
      "date": "<e.g. Q1 FY27>",
      "event": "<event description>",
      "probability": <0-100>,
      "impact_yes_pct": <positive number>,
      "impact_no_pct": <negative number, e.g. -8>
    }}
  ],
  "entry_zones": {{
    "avoid":      {{"min": <number>, "max": <number>, "reason": "<why to avoid>"}},
    "accumulate": {{"min": <number>, "max": <number>, "allocation": "<e.g. 3-5%>", "reason": "<why good entry>"}},
    "strong_buy": {{"min": <number>, "max": <number>, "allocation": "<e.g. 6-8%>", "reason": "<panic zone>"}}
  }},
  "price_distribution": {{
    "bear_case_pct":     <probability 0-100>,
    "bear_case_range":   "<e.g. 'below ₹900'>",
    "base_low_pct":      <probability 0-100>,
    "base_range":        "<e.g. '₹950 – ₹1,200'>",
    "bull_pct":          <probability 0-100>,
    "bull_range":        "<e.g. '₹1,200 – ₹1,800'>",
    "extreme_bull_pct":  <probability 0-100>,
    "extreme_bull_range":"<e.g. 'above ₹1,800'>"
  }},
  "peer_tickers": ["<NSE ticker 1>", "<NSE ticker 2>", "<NSE ticker 3>", "<NSE ticker 4>"]
}}

Rules:
- bull + bear + base probabilities MUST sum to 100
- Be specific with ₹ numbers based on current price
- peer_tickers: exact NSE symbols (no .NS suffix) of 3-4 closest sector peers
- Provide at least 2 red_flags and 3 green_flags (if any exist)
- Provide at least 3 catalysts for the next 12 months"""

        client = anthropic.Anthropic(api_key=api_key)
        resp   = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,
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
        logger.warning(f"[Conviction] Claude call failed for {symbol}: {exc}")
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

async def analyze_conviction(symbol: str) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    cached = _cache_get(f"conviction:{symbol}")
    if cached:
        return cached

    loop = asyncio.get_event_loop()

    stock_data = await loop.run_in_executor(None, _fetch_stock_data, symbol)
    if "error" in stock_data and "current_price" not in stock_data:
        return {"error": stock_data["error"], "symbol": symbol}

    conviction_data = await loop.run_in_executor(None, _generate_conviction, symbol, stock_data)
    if "error" in conviction_data:
        return {"error": conviction_data["error"], "symbol": symbol}

    peer_tickers = conviction_data.get("peer_tickers", [])
    peers: List[Dict[str, Any]] = []
    if peer_tickers:
        peers = await loop.run_in_executor(None, _fetch_peer_data, peer_tickers)

    result: Dict[str, Any] = {
        "symbol":               symbol,
        "full_name":            stock_data.get("full_name", symbol),
        "sector":               stock_data.get("sector"),
        "industry":             stock_data.get("industry"),
        "current_price":        stock_data.get("current_price"),
        "market_cap_fmt":       stock_data.get("market_cap_fmt"),
        "trailing_pe":          stock_data.get("trailing_pe"),
        "revenue_growth_pct":   stock_data.get("revenue_growth_pct"),
        "roe_pct":              stock_data.get("roe_pct"),
        "technical": {
            "rsi":               stock_data.get("rsi"),
            "rsi_signal":        stock_data.get("rsi_signal"),
            "macd_bullish":      stock_data.get("macd_bullish"),
            "bb_position":       stock_data.get("bb_position"),
            "sma_20":            stock_data.get("sma_20"),
            "sma_50":            stock_data.get("sma_50"),
            "above_sma20":       stock_data.get("above_sma20"),
            "above_sma50":       stock_data.get("above_sma50"),
            "high_52w":          stock_data.get("high_52w"),
            "low_52w":           stock_data.get("low_52w"),
            "pct_from_52w_high": stock_data.get("pct_from_52w_high"),
        },
        "conviction":           conviction_data.get("conviction"),
        "thesis":               conviction_data.get("thesis"),
        "red_flags":            conviction_data.get("red_flags", []),
        "green_flags":          conviction_data.get("green_flags", []),
        "catalysts":            conviction_data.get("catalysts", []),
        "entry_zones":          conviction_data.get("entry_zones"),
        "price_distribution":   conviction_data.get("price_distribution"),
        "peers":                peers,
        "analyzed_at":          datetime.now(_IST).strftime("%d %b %Y %H:%M IST"),
    }

    _cache_set(f"conviction:{symbol}", result)
    return result
