"""
Portfolio Optimization Service
===============================
Position sizing algorithms for swing autopilot:
1. Equal-Weight (baseline)
2. Risk-Parity (equal risk contribution)
3. Kelly Criterion (growth-optimal sizing)
4. Confidence-Weighted (higher allocation to high-confidence signals)

Uses simplified, production-ready implementations optimized for live trading.
"""
from __future__ import annotations

import numpy as np
from typing import List, Dict, Optional
from loguru import logger


class PortfolioOptimizer:
    """
    Position sizing optimizer for swing trading autopilot.

    Allocates capital across N signals to maximize risk-adjusted returns.
    """

    def __init__(self, method: str = "confidence_weighted"):
        """
        Parameters
        ----------
        method : str
            "equal_weight" | "risk_parity" | "kelly" | "confidence_weighted"
        """
        self.method = method

    def optimize(
        self,
        signals: List[Dict],
        total_capital: float,
        max_positions: int = 3
    ) -> Dict[str, float]:
        """
        Calculate optimal position sizes for each signal.

        Parameters
        ----------
        signals : List[Dict]
            Each dict must have: symbol, confidence, entry_price, stop_loss
        total_capital : float
            Total capital to allocate (e.g., ₹10,000)
        max_positions : int
            Maximum number of positions to open

        Returns
        -------
        Dict[str, float]
            symbol -> capital allocation (₹)
        """
        if not signals:
            return {}

        # Limit to top max_positions by confidence
        signals = sorted(signals, key=lambda s: s.get("confidence", 0), reverse=True)[:max_positions]

        if self.method == "equal_weight":
            return self._equal_weight(signals, total_capital)
        elif self.method == "risk_parity":
            return self._risk_parity(signals, total_capital)
        elif self.method == "kelly":
            return self._kelly_criterion(signals, total_capital)
        elif self.method == "confidence_weighted":
            return self._confidence_weighted(signals, total_capital)
        else:
            logger.warning(f"[PortfolioOptimizer] Unknown method '{self.method}' — using equal_weight")
            return self._equal_weight(signals, total_capital)

    def _equal_weight(self, signals: List[Dict], total_capital: float) -> Dict[str, float]:
        """
        Baseline: allocate equal capital to each signal.
        """
        n = len(signals)
        allocation = total_capital / n
        return {sig["symbol"]: allocation for sig in signals}

    def _risk_parity(self, signals: List[Dict], total_capital: float) -> Dict[str, float]:
        """
        Risk-Parity: allocate capital inversely proportional to risk.
        Lower stop-loss distance (lower risk) → higher allocation.

        Each position contributes equal risk to the portfolio.
        """
        allocations = {}

        # Calculate risk (stop-loss %) for each signal
        risks = []
        for sig in signals:
            entry = sig.get("entry_price", 0)
            sl = sig.get("stop_loss", 0)
            if entry <= 0 or sl <= 0:
                risks.append(0.05)  # default 5% risk if missing
            else:
                sl_pct = abs((entry - sl) / entry)
                risks.append(max(sl_pct, 0.01))  # min 1% risk floor

        # Inverse risk weights (lower risk = higher weight)
        inv_risks = [1 / r for r in risks]
        total_inv_risk = sum(inv_risks)

        # Allocate capital proportional to inverse risk
        for sig, inv_r in zip(signals, inv_risks):
            weight = inv_r / total_inv_risk
            allocations[sig["symbol"]] = weight * total_capital

        logger.info(
            f"[PortfolioOptimizer] Risk-Parity allocation: "
            + ", ".join([f"{sym}={cap:.0f}" for sym, cap in allocations.items()])
        )
        return allocations

    def _kelly_criterion(self, signals: List[Dict], total_capital: float) -> Dict[str, float]:
        """
        Kelly Criterion: f* = (p*R - (1-p)) / R
        where p = win probability (confidence), R = reward/risk ratio

        Allocates more to high-confidence, high-R:R signals.
        Uses half-Kelly (0.5 * f*) to reduce volatility.
        """
        allocations = {}
        kelly_fractions = []

        for sig in signals:
            confidence = sig.get("confidence", 0.5)  # win probability
            entry = sig.get("entry_price", 0)
            sl = sig.get("stop_loss", 0)
            target = sig.get("target1", 0)

            if entry <= 0 or sl <= 0 or target <= 0:
                kelly_fractions.append(0.10)  # default 10% if missing
                continue

            # R:R ratio = (target - entry) / (entry - sl)
            reward = target - entry
            risk = entry - sl
            rr_ratio = reward / risk if risk > 0 else 1.0

            # Kelly formula: f* = (p*R - (1-p)) / R
            # Use confidence as p (win probability)
            kelly_f = (confidence * rr_ratio - (1 - confidence)) / rr_ratio

            # Half-Kelly to reduce volatility (conservative)
            kelly_f = max(kelly_f * 0.5, 0.0)

            # Cap at 30% per position (Kelly can be aggressive)
            kelly_f = min(kelly_f, 0.30)

            kelly_fractions.append(kelly_f)

        # Normalize so total allocation <= 100%
        total_kelly = sum(kelly_fractions)
        if total_kelly > 1.0:
            kelly_fractions = [f / total_kelly for f in kelly_fractions]

        for sig, fraction in zip(signals, kelly_fractions):
            allocations[sig["symbol"]] = fraction * total_capital

        logger.info(
            f"[PortfolioOptimizer] Kelly allocation: "
            + ", ".join([f"{sym}={cap:.0f}" for sym, cap in allocations.items()])
        )
        return allocations

    def _confidence_weighted(self, signals: List[Dict], total_capital: float) -> Dict[str, float]:
        """
        Confidence-Weighted: allocate capital proportional to signal confidence.
        High-confidence signals get more capital.

        Simple, intuitive, and works well with the screener's confidence scores.
        """
        allocations = {}

        confidences = [sig.get("confidence", 0.5) for sig in signals]
        total_conf = sum(confidences)

        if total_conf == 0:
            # Fallback to equal weight if all confidences are 0
            return self._equal_weight(signals, total_capital)

        for sig, conf in zip(signals, confidences):
            weight = conf / total_conf
            allocations[sig["symbol"]] = weight * total_capital

        logger.info(
            f"[PortfolioOptimizer] Confidence-weighted allocation: "
            + ", ".join([f"{sym}={cap:.0f} ({sig['confidence']:.1%})"
                        for sig, sym, cap in zip(signals, allocations.keys(), allocations.values())])
        )
        return allocations


def get_portfolio_optimizer(method: str = "confidence_weighted") -> PortfolioOptimizer:
    """Factory function to get portfolio optimizer instance."""
    return PortfolioOptimizer(method=method)
