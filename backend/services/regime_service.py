"""
Market Regime Detection Service
================================
Detects if Nifty is trending up, trending down, ranging, or in high volatility.
Uses Vibe-Trading's ML-based regime classifier with historical win-rate statistics.

Regime Types:
- trending_up: Strong uptrend, favor momentum/breakout strategies
- trending_down: Downtrend, favor short/contrarian strategies
- ranging: Sideways consolidation, favor mean-reversion
- high_volatility: Choppy/uncertain, reduce position sizes or pause trading
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

import pytz
from loguru import logger

_IST = pytz.timezone("Asia/Kolkata")

# Cache regime detection for 15 minutes (don't re-run every request)
_regime_cache: Optional[Dict[str, Any]] = None
_cache_timestamp: Optional[datetime] = None
_CACHE_TTL_SECONDS = 900  # 15 minutes


async def detect_market_regime() -> Dict[str, Any]:
    """
    Detect current Nifty 50 market regime using Vibe-Trading's ML classifier.

    Returns:
        dict with keys:
            - regime: str ("trending_up" | "trending_down" | "ranging" | "high_volatility")
            - confidence: float (0.0-1.0)
            - recommendation: str (trading advice for current regime)
            - momentum_winrate: float (historical win rate for momentum strategies)
            - mean_reversion_winrate: float (historical win rate for mean-reversion)
            - should_trade: bool (False if regime is unfavorable)
    """
    global _regime_cache, _cache_timestamp

    # Check cache
    now = datetime.now(_IST)
    if _regime_cache and _cache_timestamp:
        elapsed = (now - _cache_timestamp).total_seconds()
        if elapsed < _CACHE_TTL_SECONDS:
            logger.debug(f"[RegimeDetection] Using cached regime (age: {elapsed:.0f}s)")
            return _regime_cache

    try:
        # Import Vibe's regime classifier
        from vibe_trading.regime import RegimeClassifier

        loop = asyncio.get_event_loop()

        # Run regime detection in executor (Vibe may use blocking I/O)
        def _detect():
            classifier = RegimeClassifier()

            # Detect regime on Nifty 50 (^NSEI is Yahoo Finance symbol)
            result = classifier.detect(
                symbol="^NSEI",
                lookback_days=20,  # Use last 20 trading days
                return_winrates=True  # Get historical strategy win rates
            )
            return result

        vibe_result = await loop.run_in_executor(None, _detect)

        # Map Vibe's result to our format
        regime_label = vibe_result.get("regime", "ranging")
        confidence = vibe_result.get("confidence", 0.5)

        # Get strategy-specific win rates
        momentum_wr = vibe_result.get("momentum_winrate", 0.55)
        mean_rev_wr = vibe_result.get("mean_reversion_winrate", 0.50)

        # Generate trading recommendation
        recommendation = _generate_recommendation(regime_label, momentum_wr, mean_rev_wr)

        # Decide if we should trade at all
        should_trade = _should_trade_in_regime(regime_label, confidence, momentum_wr)

        result = {
            "regime": regime_label,
            "confidence": round(confidence, 2),
            "recommendation": recommendation,
            "momentum_winrate": round(momentum_wr, 2),
            "mean_reversion_winrate": round(mean_rev_wr, 2),
            "should_trade": should_trade,
            "detected_at": now.strftime("%Y-%m-%d %H:%M IST"),
        }

        # Update cache
        _regime_cache = result
        _cache_timestamp = now

        logger.info(
            f"[RegimeDetection] {regime_label.upper()} "
            f"(confidence {confidence:.0%}, momentum WR {momentum_wr:.0%})"
        )

        return result

    except ImportError:
        logger.warning("[RegimeDetection] vibe-trading-ai not installed, using fallback")
        return _fallback_regime_detection()
    except Exception as exc:
        logger.error(f"[RegimeDetection] Error: {exc}")
        return _fallback_regime_detection()


def _generate_recommendation(regime: str, momentum_wr: float, mean_rev_wr: float) -> str:
    """Generate trading advice based on regime and win rates."""

    if regime == "high_volatility":
        return (
            "High volatility detected. Reduce position sizes by 50% or pause trading. "
            "Breakout signals have low success rate in choppy markets."
        )
    elif regime == "trending_up":
        return (
            f"Strong uptrend. Favor momentum and breakout strategies "
            f"(historical win rate {momentum_wr:.0%}). Avoid mean-reversion shorts."
        )
    elif regime == "trending_down":
        return (
            "Downtrend detected. Avoid long momentum trades. "
            "Consider sitting on sidelines or waiting for reversal signals."
        )
    elif regime == "ranging":
        return (
            f"Market is range-bound. Favor mean-reversion strategies "
            f"(historical win rate {mean_rev_wr:.0%}). Avoid breakout trades."
        )
    else:
        return "Regime unclear. Trade with caution and smaller position sizes."


def _should_trade_in_regime(regime: str, confidence: float, momentum_wr: float) -> bool:
    """
    Decide if autopilot should trade in this regime.

    Rules:
    - high_volatility + high confidence → NO (too risky)
    - Any regime with momentum_winrate < 45% → NO (poor odds)
    - trending_up or ranging with confidence > 70% → YES
    - Otherwise → MAYBE (let autopilot decide with smaller size)
    """

    # Hard stop: high volatility with high confidence
    if regime == "high_volatility" and confidence > 0.75:
        return False

    # Hard stop: very low historical win rate
    if momentum_wr < 0.45:
        return False

    # Green light: favorable regime with good confidence
    if regime in ("trending_up", "ranging") and confidence > 0.70:
        return True

    # Yellow light: uncertain or down-trending
    return True  # Let autopilot run but with caution flags


def _fallback_regime_detection() -> Dict[str, Any]:
    """Fallback when Vibe is unavailable — use simple heuristic."""
    logger.warning("[RegimeDetection] Using fallback heuristic (Vibe unavailable)")

    # Simple fallback: assume ranging market, allow trading
    return {
        "regime": "ranging",
        "confidence": 0.50,
        "recommendation": "Regime detection unavailable. Trading with default settings.",
        "momentum_winrate": 0.55,
        "mean_reversion_winrate": 0.50,
        "should_trade": True,
        "detected_at": datetime.now(_IST).strftime("%Y-%m-%d %H:%M IST"),
    }


def clear_regime_cache() -> None:
    """Force regime re-detection on next call (useful for testing)."""
    global _regime_cache, _cache_timestamp
    _regime_cache = None
    _cache_timestamp = None
    logger.debug("[RegimeDetection] Cache cleared")
