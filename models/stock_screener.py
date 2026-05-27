"""
stock_screener.py
=================
Swing trade screener for Nifty50 cash stocks.

Uses daily OHLCV from yfinance and the existing TechnicalFeatureEngine to
compute a multi-factor confidence score for each stock.  Only BUY signals are
generated (no short-selling on cash equities).

Signal scoring (7 factors, total weight = 1.0):
  1. Trend alignment  EMA9 > EMA21 > EMA50          — 0.35
  2. Trend strength   ADX > 20/25                   — 0.15
  3. RSI momentum     RSI in 50-70 (not overbought) — 0.15
  4. MACD histogram   positive & rising             — 0.15
  5. Volume           > 1.2x 20-day average         — 0.10
  6. Candlestick      bullish pattern               — 0.10

Entry / SL / Target:
  Entry  = latest close
  SL     = entry − 1.5 × ATR14  (below entry)
  Target1 = entry + 2 × (entry − SL)  →  1:2 R:R
  Target2 = entry + 3 × (entry − SL)  →  1:3 R:R
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import pytz
from loguru import logger

sys.path.append(str(Path(__file__).parent.parent))
from features.technical_indicators import TechnicalFeatureEngine

IST = pytz.timezone("Asia/Kolkata")
_MIN_HISTORY_BARS = 60   # minimum daily candles required to score a stock


@dataclass
class StockSignal:
    """Swing trade signal for a single Nifty50 stock."""
    symbol: str
    name: str
    sector: str
    yf_ticker: str
    action: str              # "BUY" | "HOLD"
    close: float             # latest daily close
    entry_price: float       # = close (execute at market next session)
    stop_loss: float         # entry − 1.5 × ATR14
    target1: float           # 1:2 R:R
    target2: float           # 1:3 R:R
    sl_pct: float            # SL distance as % of entry
    risk_reward: float       # always 2.0 (1:2 default)
    confidence: float        # 0.0 – 1.0 composite score
    regime: str              # "uptrend" | "downtrend" | "ranging"
    reasons: List[str] = field(default_factory=list)
    rsi: float = 0.0
    adx: float = 0.0
    atr: float = 0.0
    volume_ratio: float = 0.0
    macd_hist: float = 0.0
    ema9: float = 0.0
    ema21: float = 0.0
    ema50: float = 0.0
    rs_vs_nifty: float = 0.0   # stock 20d return minus Nifty 20d return (%)
    scan_time: datetime = field(default_factory=lambda: datetime.now(IST))

    def to_dict(self) -> dict:
        return {
            "symbol":        self.symbol,
            "name":          self.name,
            "sector":        self.sector,
            "yf_ticker":     self.yf_ticker,
            "action":        self.action,
            "close":         self.close,
            "entry_price":   self.entry_price,
            "stop_loss":     self.stop_loss,
            "target1":       self.target1,
            "target2":       self.target2,
            "sl_pct":        self.sl_pct,
            "risk_reward":   self.risk_reward,
            "confidence":    round(self.confidence, 4),
            "regime":        self.regime,
            "reasons":       self.reasons,
            "rsi":           round(self.rsi, 2),
            "adx":           round(self.adx, 2),
            "atr":           round(self.atr, 2),
            "volume_ratio":  round(self.volume_ratio, 2),
            "macd_hist":     round(self.macd_hist, 4),
            "ema9":          round(self.ema9, 2),
            "ema21":         round(self.ema21, 2),
            "ema50":         round(self.ema50, 2),
            "rs_vs_nifty":   round(self.rs_vs_nifty, 2),
            "scan_time":     self.scan_time.isoformat(),
        }


class StockScreener:
    """
    Scans the Nifty50 universe for swing trade setups using daily candles.

    Parameters
    ----------
    config : dict
        Full application config (trading_config from BackendConfig).
        Expected key: stocks.min_confidence (default 0.55)
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        stocks_cfg = config.get("stocks", {})
        self.min_confidence: float = float(stocks_cfg.get("min_confidence", 0.55))
        self._feature_engine = TechnicalFeatureEngine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_swing(self, universe: list) -> List[StockSignal]:
        """
        Scan every stock in *universe* and return actionable BUY signals,
        sorted by confidence descending.

        Parameters
        ----------
        universe : list of dict
            Each dict: {"symbol": str, "name": str, "sector": str, "yf": str}

        Returns
        -------
        List[StockSignal]  — only BUY signals with confidence >= min_confidence
        """
        import yfinance as yf

        # ── Gate 1: Nifty market regime ──────────────────────────────
        # Only take stock longs when Nifty50 itself is in an uptrend
        # (close > 200-day EMA). Avoids buying individual stocks in a
        # broad bear market.
        nifty_bullish, nifty_20d_ret = self._get_nifty_regime()
        if not nifty_bullish:
            logger.warning(
                "[Screener] Nifty50 is BELOW its 200-day EMA — "
                "broad market is bearish. Skipping swing scan."
            )
            return []
        logger.info(
            f"[Screener] Nifty regime: BULLISH (20d return={nifty_20d_ret:+.1f}%). "
            "Proceeding with stock scan."
        )

        signals: List[StockSignal] = []

        for stock in universe:
            try:
                sig = self._scan_stock(stock, nifty_20d_ret)
                if sig is not None and sig.action == "BUY" and sig.confidence >= self.min_confidence:
                    signals.append(sig)
            except Exception as exc:
                logger.warning(f"[Screener] {stock['symbol']}: skipped — {exc}")

        signals.sort(key=lambda s: s.confidence, reverse=True)
        logger.info(
            f"[Screener] Scan complete. {len(universe)} stocks scanned, "
            f"{len(signals)} BUY signals found."
        )
        return signals

    # ------------------------------------------------------------------
    # Nifty regime & relative strength helpers
    # ------------------------------------------------------------------

    def _get_nifty_regime(self) -> tuple[bool, float]:
        """
        Fetch ^NSEI daily data and return:
          - bullish: True if close > 200-day EMA
          - nifty_20d_ret: Nifty's 20-day return (%) used for RS comparison
        Returns (True, 0.0) on fetch failure so a data glitch doesn't
        block all trading.
        """
        import yfinance as yf
        try:
            df = yf.download("^NSEI", period="250d", interval="1d",
                             progress=False, auto_adjust=True)
            if df is None or len(df) < 50:
                return True, 0.0
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            close = df["close"].dropna()
            ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
            bullish = float(close.iloc[-1]) > float(ema200)
            # 20-day return for relative strength comparison
            nifty_20d_ret = (float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100 if len(close) > 21 else 0.0
            return bullish, nifty_20d_ret
        except Exception as exc:
            logger.warning(f"[Screener] Nifty regime fetch failed: {exc} — assuming bullish")
            return True, 0.0

    # ------------------------------------------------------------------
    # Per-stock logic
    # ------------------------------------------------------------------

    def _scan_stock(self, stock: dict, nifty_20d_ret: float = 0.0) -> Optional[StockSignal]:
        """Fetch daily OHLCV, compute features, score, return StockSignal or None."""
        import yfinance as yf

        ticker = stock["yf"]
        df = yf.download(ticker, period="200d", interval="1d", progress=False, auto_adjust=True)

        if df is None or df.empty or len(df) < _MIN_HISTORY_BARS:
            logger.debug(f"[Screener] {stock['symbol']}: insufficient data ({len(df) if df is not None else 0} bars)")
            return None

        # Flatten MultiIndex columns (yfinance sometimes returns them)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Lowercase column names for TechnicalFeatureEngine
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"adj close": "close"}) if "adj close" in df.columns else df
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df = df.dropna()

        if len(df) < _MIN_HISTORY_BARS:
            return None

        # Compute all technical features
        df = self._feature_engine.compute_all(df)

        return self._score_signal(stock, df, nifty_20d_ret)

    def _score_signal(self, stock: dict, df: pd.DataFrame, nifty_20d_ret: float = 0.0) -> StockSignal:
        """
        Apply the 8-factor scoring model to the latest bar of *df*.
        Returns a StockSignal (action may be "HOLD" if score < threshold).

        Factors (total weight = 1.10 before normalisation):
          1. Trend alignment EMA9/21/50       — 0.35
          2. Trend strength ADX               — 0.15
          3. RSI momentum zone                — 0.15
          4. MACD histogram positive/rising   — 0.15
          5. Volume confirmation              — 0.10
          6. Bullish candlestick pattern      — 0.10
          7. Relative strength vs Nifty       — 0.10 (NEW)
        """
        row  = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else row

        close    = float(row.get("close", 0))
        ema9     = float(row.get("ema_9",  close))
        ema21    = float(row.get("ema_21", close))
        ema50    = float(row.get("ema_50", close))
        rsi      = float(row.get("rsi", 50))
        adx      = float(row.get("adx", 0))
        macd_h   = float(row.get("macd_hist", 0))
        prev_mh  = float(prev.get("macd_hist", 0))
        atr14    = float(df["atr"].rolling(14).mean().iloc[-1]) if "atr" in df.columns else close * 0.02
        volume   = float(row.get("volume", 0))
        avg_vol  = float(df["volume"].rolling(20).mean().iloc[-1]) if "volume" in df.columns else 1
        vol_ratio = volume / avg_vol if avg_vol > 0 else 1.0
        bull_eng = bool(row.get("pattern_bull_engulfing", 0))
        hammer   = bool(row.get("pattern_hammer", 0))

        # ── Relative strength: stock 20-day return vs Nifty ──────────
        stock_20d_ret = 0.0
        if len(df) > 21:
            close_series = df["close"].dropna()
            stock_20d_ret = (float(close_series.iloc[-1]) / float(close_series.iloc[-21]) - 1) * 100

        score   = 0.0
        reasons = []

        # ── 1. Trend alignment (35%) ──────────────────────────────────
        if close > ema21 and ema21 > ema50:
            score += 0.20
            reasons.append("Close > EMA21 > EMA50 (trend aligned)")
        elif close > ema21:
            score += 0.10
            reasons.append("Close > EMA21")
        if ema9 > ema21:
            score += 0.15
            reasons.append("EMA9 > EMA21 (short-term bullish)")

        # ── 2. Trend strength ADX (15%) ──────────────────────────────
        if adx > 25:
            score += 0.15
            reasons.append(f"ADX={adx:.1f} > 25 (strong trend)")
        elif adx > 20:
            score += 0.08
            reasons.append(f"ADX={adx:.1f} > 20 (moderate trend)")

        # ── 3. RSI momentum zone (15%) ───────────────────────────────
        if 50 <= rsi <= 70:
            score += 0.15
            reasons.append(f"RSI={rsi:.1f} in 50–70 (momentum zone)")
        elif 45 <= rsi < 50:
            score += 0.07
            reasons.append(f"RSI={rsi:.1f} approaching 50")

        # ── 4. MACD histogram positive & rising (15%) ────────────────
        if macd_h > 0 and macd_h > prev_mh:
            score += 0.15
            reasons.append("MACD histogram positive & rising")
        elif macd_h > 0:
            score += 0.08
            reasons.append("MACD histogram positive")

        # ── 5. Volume confirmation (10%) ─────────────────────────────
        if vol_ratio >= 1.5:
            score += 0.10
            reasons.append(f"Volume {vol_ratio:.1f}x avg (strong)")
        elif vol_ratio >= 1.2:
            score += 0.05
            reasons.append(f"Volume {vol_ratio:.1f}x avg")

        # ── 6. Bullish candlestick (10%) ─────────────────────────────
        if bull_eng or hammer:
            score += 0.10
            pat = "Bull Engulfing" if bull_eng else "Hammer"
            reasons.append(f"Candlestick: {pat}")

        # ── 7. Relative strength vs Nifty50 (10%) ───────────────────
        # Stock outperforming Nifty over the last 20 days means
        # institutional/smart money is rotating into this name.
        rs_diff = stock_20d_ret - nifty_20d_ret
        if rs_diff >= 3.0:
            score += 0.10
            reasons.append(f"RS vs Nifty: +{rs_diff:.1f}% outperformance (strong)")
        elif rs_diff >= 1.0:
            score += 0.05
            reasons.append(f"RS vs Nifty: +{rs_diff:.1f}% outperformance")
        elif rs_diff < -2.0:
            # Underperforming the index — penalise
            score -= 0.05
            reasons.append(f"RS vs Nifty: {rs_diff:.1f}% (lagging index)")

        # ── Regime label ─────────────────────────────────────────────
        if ema9 > ema21 > ema50 and adx > 20:
            regime = "uptrend"
        elif ema9 < ema21 < ema50 and adx > 20:
            regime = "downtrend"
        else:
            regime = "ranging"

        action = "BUY" if score >= self.min_confidence else "HOLD"

        # ── Entry / SL / Target ──────────────────────────────────────
        entry    = round(close, 2)
        sl       = round(entry - 1.5 * atr14, 2)
        sl       = max(sl, entry * 0.85)  # cap SL at 15% below entry
        sl_dist  = entry - sl
        target1  = round(entry + 2.0 * sl_dist, 2)
        target2  = round(entry + 3.0 * sl_dist, 2)
        sl_pct   = round(sl_dist / entry * 100, 2)

        return StockSignal(
            symbol      = stock["symbol"],
            name        = stock["name"],
            sector      = stock["sector"],
            yf_ticker   = stock["yf"],
            action      = action,
            close       = entry,
            entry_price = entry,
            stop_loss   = sl,
            target1     = target1,
            target2     = target2,
            sl_pct      = sl_pct,
            risk_reward = 2.0,
            confidence  = round(min(max(score, 0.0), 1.0), 4),
            regime      = regime,
            reasons     = reasons,
            rsi         = rsi,
            adx         = adx,
            atr         = round(atr14, 2),
            volume_ratio= round(vol_ratio, 2),
            macd_hist   = round(macd_h, 4),
            ema9        = round(ema9, 2),
            ema21       = round(ema21, 2),
            ema50       = round(ema50, 2),
            rs_vs_nifty = round(stock_20d_ret - nifty_20d_ret, 2),
        )
