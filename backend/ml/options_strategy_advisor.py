"""
Options Strategy Advisor — Comprehensive options trading strategy engine.
Analyzes market conditions and recommends optimal spreads with full calculations.
"""

import numpy as np
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
from loguru import logger

_IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class OptionsSpread:
    """Represents an options spread strategy"""
    name: str
    description: str
    legs: List[Dict]  # Each leg: {"type": "CALL/PUT", "strike": X, "position": "BUY/SELL", "qty": 1}
    outlook: str  # "BULLISH", "BEARISH", "NEUTRAL"
    max_profit: float
    max_loss: float
    breakeven_points: List[float]
    probability_profit: float  # 0-100%
    capital_required: float
    reward_risk_ratio: float


@dataclass
class MarketAnalysis:
    """Current market analysis and setup"""
    nifty_price: float
    daily_change: float
    daily_change_pct: float
    volatility: float  # IV percentile 0-100
    trend: str  # "STRONG_BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "STRONG_BEARISH"
    support_level: float
    resistance_level: float
    distance_to_support: float  # percentage
    distance_to_resistance: float  # percentage
    rsi: float
    macd_signal: str  # "BULLISH", "BEARISH"
    range_high: float  # today's high
    range_low: float  # today's low
    volume_ratio: float  # current vs 20-day avg
    timestamp: str


@dataclass
class StrategyRecommendation:
    """Recommended strategy with calculations"""
    primary_strategy: OptionsSpread
    alternative_strategies: List[OptionsSpread]
    market_analysis: MarketAnalysis
    rationale: str  # Why this strategy for current market
    risk_factors: List[str]
    profit_targets: Dict[str, float]  # At different price levels
    stop_loss_level: float
    ideal_entry_time: str
    expiry_days: int
    timestamp: str


class OptionsStrategyAdvisor:
    """Options strategy recommendation engine"""

    SPREADS_LIBRARY = {
        # BULLISH strategies
        "bull_call_spread": {
            "name": "Bull Call Spread",
            "description": "Buy ATM call, Sell OTM call. Limited profit & loss.",
            "outlook": "BULLISH",
            "risk_level": "LOW",
            "capital_efficiency": "HIGH",
            "max_profit_potential": "LIMITED",
            "ideal_for": "Moderate bullish with limited capital",
        },
        "bull_put_spread": {
            "name": "Bull Put Spread",
            "description": "Sell OTM put, Buy further OTM put. Collect premium.",
            "outlook": "BULLISH",
            "risk_level": "LOW",
            "capital_efficiency": "HIGH",
            "max_profit_potential": "LIMITED",
            "ideal_for": "Bullish with income focus",
        },
        "call_ratio_spread": {
            "name": "Call Ratio Spread",
            "description": "Buy ATM call, Sell 2x OTM calls. Income with limited risk.",
            "outlook": "BULLISH",
            "risk_level": "MEDIUM",
            "capital_efficiency": "MEDIUM",
            "max_profit_potential": "HIGH",
            "ideal_for": "Strong bullish, defined support",
        },

        # BEARISH strategies
        "bear_call_spread": {
            "name": "Bear Call Spread",
            "description": "Sell ATM call, Buy OTM call. Collect premium.",
            "outlook": "BEARISH",
            "risk_level": "LOW",
            "capital_efficiency": "HIGH",
            "max_profit_potential": "LIMITED",
            "ideal_for": "Bearish with income focus",
        },
        "bear_put_spread": {
            "name": "Bear Put Spread",
            "description": "Sell ATM put, Buy OTM put. Defined risk.",
            "outlook": "BEARISH",
            "risk_level": "LOW",
            "capital_efficiency": "HIGH",
            "max_profit_potential": "LIMITED",
            "ideal_for": "Moderate bearish with limited capital",
        },

        # NEUTRAL strategies
        "iron_condor": {
            "name": "Iron Condor",
            "description": "Sell call spread + Sell put spread. Neutral range play.",
            "outlook": "NEUTRAL",
            "risk_level": "LOW",
            "capital_efficiency": "HIGH",
            "max_profit_potential": "HIGH",
            "ideal_for": "Neutral/ranging market, income generation",
        },
        "short_straddle": {
            "name": "Short Straddle",
            "description": "Sell ATM call + Sell ATM put. Profit from low volatility.",
            "outlook": "NEUTRAL",
            "risk_level": "HIGH",
            "capital_efficiency": "MEDIUM",
            "max_profit_potential": "HIGH",
            "ideal_for": "Low volatility, strong support/resistance",
        },
        "short_strangle": {
            "name": "Short Strangle",
            "description": "Sell OTM call + Sell OTM put. Reduced risk vs straddle.",
            "outlook": "NEUTRAL",
            "risk_level": "MEDIUM",
            "capital_efficiency": "HIGH",
            "max_profit_potential": "HIGH",
            "ideal_for": "Neutral, reduced gamma risk",
        },
    }

    def __init__(self):
        self.last_analysis = None

    @staticmethod
    def classify_trend(rsi: float, macd_signal: str, sma_position: str) -> str:
        """Classify market trend based on indicators"""
        bullish_signals = 0
        if rsi > 60:
            bullish_signals += 1
        if macd_signal == "BULLISH":
            bullish_signals += 1
        if sma_position == "above":
            bullish_signals += 1

        if bullish_signals >= 3:
            return "STRONG_BULLISH"
        elif bullish_signals == 2:
            return "BULLISH"
        elif bullish_signals == 1:
            return "NEUTRAL"
        elif bullish_signals == 0 and macd_signal == "BEARISH":
            return "BEARISH"
        else:
            return "NEUTRAL"

    @staticmethod
    def select_spreads_for_outlook(outlook: str) -> List[str]:
        """Select best spreads for given market outlook"""
        if outlook in ("STRONG_BULLISH", "BULLISH"):
            return ["bull_call_spread", "bull_put_spread", "call_ratio_spread"]
        elif outlook in ("STRONG_BEARISH", "BEARISH"):
            return ["bear_call_spread", "bear_put_spread"]
        else:  # NEUTRAL
            return ["iron_condor", "short_strangle", "short_straddle"]

    def analyze_market(
        self,
        nifty_price: float,
        prev_close: float,
        volatility: float,
        rsi: float,
        macd_signal: str,
        sma50: float,
        support: float,
        resistance: float,
        range_high: float,
        range_low: float,
        volume_ratio: float,
    ) -> MarketAnalysis:
        """Analyze current market conditions"""
        daily_change = nifty_price - prev_close
        daily_change_pct = (daily_change / prev_close) * 100

        # Classify trend
        sma_position = "above" if nifty_price > sma50 else "below"
        trend = self.classify_trend(rsi, macd_signal, sma_position)

        # Calculate distances to support/resistance
        distance_to_support = ((nifty_price - support) / support) * 100
        distance_to_resistance = ((resistance - nifty_price) / resistance) * 100

        analysis = MarketAnalysis(
            nifty_price=nifty_price,
            daily_change=daily_change,
            daily_change_pct=daily_change_pct,
            volatility=volatility,  # IV percentile
            trend=trend,
            support_level=support,
            resistance_level=resistance,
            distance_to_support=distance_to_support,
            distance_to_resistance=distance_to_resistance,
            rsi=rsi,
            macd_signal=macd_signal,
            range_high=range_high,
            range_low=range_low,
            volume_ratio=volume_ratio,
            timestamp=datetime.now(_IST).isoformat(),
        )

        self.last_analysis = analysis
        return analysis

    def calculate_spread_Greeks(
        self,
        legs: List[Dict],
        nifty_price: float,
        iv: float,
        days_to_expiry: int,
        risk_free_rate: float = 0.06,
    ) -> Dict:
        """Calculate combined Greeks for a spread"""
        from backend.ml.nifty_options_trader import NiftyOptionsTrader

        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        total_premium_paid = 0.0
        total_premium_received = 0.0

        trader = NiftyOptionsTrader.get_instance()

        for leg in legs:
            leg_type = leg["type"]  # CALL or PUT
            strike = leg["strike"]
            position = leg["position"]  # BUY or SELL
            qty = leg.get("qty", 1)

            # Calculate Greeks for this leg
            greeks = trader._black_scholes(
                S=nifty_price,
                K=strike,
                T=days_to_expiry / 365.0,
                r=risk_free_rate,
                sigma=iv / 100.0,
                option_type=leg_type,
            )

            # Apply position direction (long = +, short = -)
            multiplier = 1 if position == "BUY" else -1

            total_delta += greeks["delta"] * multiplier * qty
            total_gamma += greeks["gamma"] * multiplier * qty
            total_theta += greeks["theta"] * multiplier * qty * 365  # Convert to daily
            total_vega += greeks["vega"] * multiplier * qty

            # Track premium flow
            premium = greeks["premium"] * 100 * qty  # Per lot (100 units)
            if position == "BUY":
                total_premium_paid += premium
            else:
                total_premium_received += premium

        net_premium = total_premium_received - total_premium_paid

        return {
            "delta": total_delta,
            "gamma": total_gamma,
            "theta": total_theta / 100,  # Per point move
            "vega": total_vega,
            "net_premium": net_premium,
            "premium_paid": total_premium_paid,
            "premium_received": total_premium_received,
        }

    def calculate_spread_payoff(
        self, legs: List[Dict], strike_range: np.ndarray, expiry_premium: float = 0
    ) -> Tuple[np.ndarray, Dict]:
        """Calculate P&L across strike range"""
        payoff = np.zeros_like(strike_range, dtype=float)

        for leg in legs:
            leg_type = leg["type"]
            strike = leg["strike"]
            position = leg["position"]
            qty = leg.get("qty", 1)

            if leg_type == "CALL":
                intrinsic = np.maximum(strike_range - strike, 0)
            else:  # PUT
                intrinsic = np.maximum(strike - strike_range, 0)

            # Apply position
            multiplier = qty if position == "BUY" else -qty
            payoff += intrinsic * multiplier

        # Subtract net premium paid
        payoff -= expiry_premium

        max_profit = float(np.max(payoff))
        max_loss = float(np.min(payoff))

        # Find breakeven points
        breakevens = []
        zero_crossings = np.where(np.diff(np.sign(payoff)))[0]
        for idx in zero_crossings:
            # Linear interpolation between points
            if idx < len(strike_range) - 1:
                x1, x2 = strike_range[idx], strike_range[idx + 1]
                y1, y2 = payoff[idx], payoff[idx + 1]
                if y2 != y1:  # Avoid division by zero
                    be = x1 - y1 * (x2 - x1) / (y2 - y1)
                    breakevens.append(float(be))

        return payoff, {
            "max_profit": max_profit,
            "max_loss": max_loss,
            "breakeven_points": sorted(set([round(be, 2) for be in breakevens])),
        }

    def build_spread(
        self,
        spread_key: str,
        nifty_price: float,
        iv: float,
        days_to_expiry: int,
    ) -> Optional[OptionsSpread]:
        """Build a complete spread with all calculations"""
        if spread_key not in self.SPREADS_LIBRARY:
            return None

        spec = self.SPREADS_LIBRARY[spread_key]

        # Build legs based on spread type
        legs = self._build_spread_legs(spread_key, nifty_price, iv, days_to_expiry)

        if not legs:
            return None

        # Calculate Greeks
        greeks = self.calculate_spread_Greeks(legs, nifty_price, iv, days_to_expiry)

        # Calculate payoff
        strike_range = np.arange(nifty_price - 500, nifty_price + 500, 10)
        payoff, payoff_stats = self.calculate_spread_payoff(
            legs, strike_range, greeks["net_premium"]
        )

        # Calculate capital required
        if spread_key in ("bull_call_spread", "bear_put_spread", "bear_call_spread", "bull_put_spread"):
            capital_required = abs(payoff_stats["max_loss"])
        else:
            capital_required = max(abs(payoff_stats["max_loss"]), greeks["premium_paid"])

        # Calculate reward/risk
        max_profit = payoff_stats["max_profit"]
        max_loss = abs(payoff_stats["max_loss"])
        rr_ratio = max_profit / max_loss if max_loss > 0 else 0

        # Estimate probability of profit
        prob_profit = self._estimate_prob_profit(nifty_price, payoff_stats["breakeven_points"], iv)

        return OptionsSpread(
            name=spec["name"],
            description=spec["description"],
            legs=legs,
            outlook=spec["outlook"],
            max_profit=max_profit,
            max_loss=max_loss,
            breakeven_points=payoff_stats["breakeven_points"],
            probability_profit=prob_profit,
            capital_required=capital_required,
            reward_risk_ratio=rr_ratio,
        )

    def _build_spread_legs(
        self, spread_key: str, nifty_price: float, iv: float, days_to_expiry: int
    ) -> List[Dict]:
        """Build legs for a specific spread"""
        atm_strike = round(nifty_price / 100) * 100
        otm_100 = atm_strike + 100
        otm_200 = atm_strike + 200
        itm_strike = atm_strike - 100

        legs_map = {
            "bull_call_spread": [
                {"type": "CALL", "strike": atm_strike, "position": "BUY", "qty": 1},
                {"type": "CALL", "strike": otm_100, "position": "SELL", "qty": 1},
            ],
            "bull_put_spread": [
                {"type": "PUT", "strike": atm_strike, "position": "SELL", "qty": 1},
                {"type": "PUT", "strike": itm_strike, "position": "BUY", "qty": 1},
            ],
            "bear_call_spread": [
                {"type": "CALL", "strike": atm_strike, "position": "SELL", "qty": 1},
                {"type": "CALL", "strike": otm_100, "position": "BUY", "qty": 1},
            ],
            "bear_put_spread": [
                {"type": "PUT", "strike": atm_strike, "position": "SELL", "qty": 1},
                {"type": "PUT", "strike": otm_100, "position": "BUY", "qty": 1},
            ],
            "iron_condor": [
                {"type": "CALL", "strike": atm_strike, "position": "SELL", "qty": 1},
                {"type": "CALL", "strike": otm_100, "position": "BUY", "qty": 1},
                {"type": "PUT", "strike": atm_strike, "position": "SELL", "qty": 1},
                {"type": "PUT", "strike": itm_strike, "position": "BUY", "qty": 1},
            ],
            "short_straddle": [
                {"type": "CALL", "strike": atm_strike, "position": "SELL", "qty": 1},
                {"type": "PUT", "strike": atm_strike, "position": "SELL", "qty": 1},
            ],
            "short_strangle": [
                {"type": "CALL", "strike": otm_100, "position": "SELL", "qty": 1},
                {"type": "PUT", "strike": itm_strike, "position": "SELL", "qty": 1},
            ],
            "call_ratio_spread": [
                {"type": "CALL", "strike": atm_strike, "position": "BUY", "qty": 1},
                {"type": "CALL", "strike": otm_100, "position": "SELL", "qty": 2},
            ],
        }

        return legs_map.get(spread_key, [])

    @staticmethod
    def _estimate_prob_profit(
        current_price: float, breakeven_points: List[float], iv: float
    ) -> float:
        """Estimate probability of profit based on breakevens and IV"""
        if not breakeven_points:
            return 50.0

        # Simple estimation: higher IV = lower prob of profit for credit spreads
        base_prob = 50.0

        # If two breakevens exist, price needs to stay between them
        if len(breakeven_points) == 2:
            be_lower, be_upper = sorted(breakeven_points)
            midpoint = (be_lower + be_upper) / 2
            distance = (be_upper - be_lower) / 2

            # Assume 1 SD move = ~68% probability
            # Distance as percentage of current price
            distance_pct = (distance / current_price) * 100

            # Higher IV means wider expected moves = lower prob of staying in range
            prob_profit = 50 + (20 - distance_pct) - (iv / 10)
            return max(20.0, min(80.0, prob_profit))

        return base_prob

    def recommend_strategy(
        self, market_analysis: MarketAnalysis, iv_percentile: float = 50
    ) -> StrategyRecommendation:
        """Generate complete strategy recommendation"""
        # Select best spreads for current trend
        candidate_spreads = self.select_spreads_for_outlook(market_analysis.trend)

        recommendations = []
        for spread_key in candidate_spreads:
            spread = self.build_spread(
                spread_key,
                market_analysis.nifty_price,
                market_analysis.volatility,
                days_to_expiry=14,  # Default to weekly
            )
            if spread:
                recommendations.append(spread)

        if not recommendations:
            logger.warning("[StrategyAdvisor] No valid spreads generated")
            return None

        # Sort by reward/risk ratio
        recommendations.sort(key=lambda s: s.reward_risk_ratio, reverse=True)
        primary = recommendations[0]

        # Generate rationale
        rationale = self._generate_rationale(market_analysis, primary)

        # Determine stop loss
        sl_level = market_analysis.support_level - 50

        # Determine entry time
        entry_time = "Market Open (09:15)" if market_analysis.volume_ratio > 0.8 else "After 10:30"

        return StrategyRecommendation(
            primary_strategy=primary,
            alternative_strategies=recommendations[1:],
            market_analysis=market_analysis,
            rationale=rationale,
            risk_factors=self._identify_risk_factors(market_analysis),
            profit_targets={
                "25%": primary.max_profit * 0.25,
                "50%": primary.max_profit * 0.50,
                "75%": primary.max_profit * 0.75,
                "100%": primary.max_profit,
            },
            stop_loss_level=sl_level,
            ideal_entry_time=entry_time,
            expiry_days=14,
            timestamp=datetime.now(_IST).isoformat(),
        )

    @staticmethod
    def _generate_rationale(analysis: MarketAnalysis, strategy: OptionsSpread) -> str:
        """Generate explanation for strategy choice"""
        return (
            f"Market is {analysis.trend.lower()}. "
            f"NIFTY at {analysis.nifty_price:.0f} ({analysis.daily_change_pct:+.2f}%). "
            f"RSI={analysis.rsi:.0f}, IV={analysis.volatility:.0f}th percentile. "
            f"{strategy.name} offers {strategy.reward_risk_ratio:.2f}:1 risk/reward "
            f"with {strategy.probability_profit:.0f}% probability of profit."
        )

    @staticmethod
    def _identify_risk_factors(analysis: MarketAnalysis) -> List[str]:
        """Identify key risks in current market"""
        risks = []

        if analysis.volatility < 30:
            risks.append("Low volatility - limited premium collection opportunity")
        elif analysis.volatility > 80:
            risks.append("High volatility - wider unexpected moves possible")

        if abs(analysis.daily_change_pct) > 1.0:
            risks.append(f"High intraday move already ({analysis.daily_change_pct:+.2f}%)")

        if analysis.distance_to_support < 3.0:
            risks.append(f"Close to support ({analysis.distance_to_support:.1f}%) - breakout possible")

        if analysis.distance_to_resistance < 3.0:
            risks.append(f"Close to resistance ({analysis.distance_to_resistance:.1f}%) - pullback likely")

        if analysis.volume_ratio < 0.8:
            risks.append("Below-average volume - liquidity concern")

        return risks if risks else ["Standard market conditions"]


# Singleton instance
_strategy_advisor_instance = None


def get_strategy_advisor() -> OptionsStrategyAdvisor:
    """Get or create strategy advisor singleton"""
    global _strategy_advisor_instance
    if _strategy_advisor_instance is None:
        _strategy_advisor_instance = OptionsStrategyAdvisor()
    return _strategy_advisor_instance
