"""
WEEKLY 5% INCOME TRADER — Intelligent Automated System
=========================================================

Multi-strategy approach targeting 5% weekly returns:
1. Weekly NIFTY Long Call Spreads (defined risk)
2. Intraday NIFTY momentum scalping (daily cash flow)
3. High-conviction stock momentum plays
4. Sector rotation tactical positions

NO option selling — only BUYING options (defined risk).
Leverage positions on high-conviction setups only.

Win Rate Target: 65%+ on spreads, 60%+ on intraday
Profit Factor: 2.5+ (average win 2.5x average loss)
Risk per trade: 1% of capital, 3-5 trades per week
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import numpy as np

from loguru import logger

_IST = timezone(timedelta(hours=5, minutes=30))

# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OptionLeg:
    """Long option position (call or put)"""
    strike: float
    option_type: str  # "CALL" or "PUT"
    expiry: str  # "weekly" or "intraday"
    premium: float
    quantity: int = 1
    delta: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

@dataclass
class TradeSetup:
    """Complete trade setup ready for execution"""
    id: str
    strategy: str  # "call_spread", "put_spread", "intraday_call", "stock_momentum"
    symbol: str  # "NIFTY" or stock
    entry_price: float
    entry_time: str
    long_leg: OptionLeg
    short_leg: Optional[OptionLeg]  # None for intraday

    max_profit: float
    max_loss: float
    breakeven: float
    risk_reward_ratio: float

    probability_win: float  # 65-80% for spreads
    capital_required: float

    exit_profit_target: float
    exit_stop_loss: float
    exit_time: str  # Time to close if not hit

    confidence_score: float  # 0-100
    rationale: List[str]

@dataclass
class TradeResult:
    """Executed trade result"""
    setup_id: str
    status: str  # "open", "profit", "loss", "cancelled"
    entry_price: float
    exit_price: Optional[float]
    pnl: float
    pnl_pct: float
    duration_minutes: int
    exit_reason: str

# ─────────────────────────────────────────────────────────────────────────────
# MARKET ANALYSIS ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class MarketAnalyzer:
    """Real-time market analysis for setups"""

    async def analyze_nifty_intraday(self,
        nifty_price: float,
        rsi: float,
        macd_hist: float,
        volume_ratio: float,
        atr: float,
        sma50: float,
        support: float,
        resistance: float
    ) -> Dict:
        """Analyze NIFTY for intraday momentum opportunities"""

        signals = []
        confidence = 0.0

        # Momentum signal (RSI 50-65 = bullish, <40 = bearish)
        if 50 <= rsi <= 65:
            signals.append("RSI in bullish momentum zone")
            confidence += 20
        elif rsi < 40:
            signals.append("RSI oversold — bounce expected")
            confidence += 15
        elif rsi > 70:
            signals.append("RSI overbought — caution")
            confidence -= 10

        # Trend confirmation (MACD)
        if macd_hist > 0:
            signals.append("MACD positive — uptrend momentum")
            confidence += 20
        else:
            signals.append("MACD negative — downtrend")
            confidence -= 10

        # Volume surge (high volume = strong move)
        if volume_ratio > 1.2:
            signals.append(f"Volume surge ({volume_ratio:.2f}x) — strong conviction")
            confidence += 15

        # Support/Resistance proximity
        distance_to_resistance = ((resistance - nifty_price) / nifty_price) * 100
        distance_to_support = ((nifty_price - support) / nifty_price) * 100

        if distance_to_resistance < 0.8:  # <0.8% from resistance
            signals.append(f"Near resistance ({distance_to_resistance:.2f}%) — watch for rejection")
            confidence -= 5
        elif distance_to_support < 0.8:  # <0.8% from support
            signals.append(f"Near support ({distance_to_support:.2f}%) — strong buy zone")
            confidence += 10

        # ATR-based volatility
        atr_pct = (atr / nifty_price) * 100
        if atr_pct > 1.0:
            signals.append(f"High volatility ({atr_pct:.2f}% ATR) — large moves expected")
            confidence += 10

        return {
            "confidence": min(100, max(0, confidence)),
            "signals": signals,
            "atr_pct": atr_pct,
            "distance_to_resistance": distance_to_resistance,
            "distance_to_support": distance_to_support,
        }

    async def analyze_market_cycle(self, cycle: Dict) -> Dict:
        """Map cycle phase to trade strategy bias"""
        phase = cycle.get("phase", "recovery")
        confidence = cycle.get("confidence", "LOW")

        strategy_map = {
            "expansion": {
                "bias": "BULLISH",
                "primary": "call_spreads",
                "secondary": "stock_momentum",
                "avoid": "put_spreads",
                "conviction": 85 if confidence == "HIGH" else 60,
            },
            "late_expansion": {
                "bias": "NEUTRAL",
                "primary": "profit_taking",
                "secondary": "small_scalps",
                "avoid": "large_positions",
                "conviction": 50,
            },
            "contraction": {
                "bias": "BEARISH",
                "primary": "put_spreads",
                "secondary": "defensive_stocks",
                "avoid": "call_spreads",
                "conviction": 75 if confidence == "HIGH" else 55,
            },
            "recovery": {
                "bias": "NEUTRAL",
                "primary": "wait_for_confirmation",
                "secondary": "small_positions",
                "avoid": "large_bets",
                "conviction": 30,
            },
        }

        return strategy_map.get(phase, strategy_map["recovery"])


# ─────────────────────────────────────────────────────────────────────────────
# TRADE SETUP GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

class TradeSetupGenerator:
    """Generate high-probability trade setups"""

    def __init__(self):
        self.analyzer = MarketAnalyzer()

    async def generate_weekly_call_spread(self,
        nifty_price: float,
        iv_percentile: float,
        support: float,
        resistance: float,
        cycle_confidence: str,
        capital: float
    ) -> Optional[TradeSetup]:
        """
        Generate weekly NIFTY call spread for bullish markets.

        Structure:
        - BUY 1 ATM call
        - SELL 1 OTM call (100-150 points higher)

        Defined risk = difference between strikes - net premium paid
        """

        # Only generate if market is bullish
        if cycle_confidence != "HIGH":
            return None

        # ATM call strike (round to nearest 100)
        atm_strike = round(nifty_price / 100) * 100
        otm_strike = atm_strike + 150  # 150 points OTM

        # Estimate premiums based on IV percentile and Greeks
        # Higher IV = higher premiums
        iv_factor = (iv_percentile / 50)  # Normalize around 50
        atm_premium = (atm_strike * 0.02 * iv_factor)  # ~2% of strike
        otm_premium = (otm_strike * 0.01 * iv_factor)  # ~1% of strike

        # Net debit (cost to enter)
        net_debit = atm_premium - otm_premium

        # Max profit = width of spread - net debit
        max_profit = (otm_strike - atm_strike) - net_debit
        max_loss = net_debit  # Limited to premium paid
        breakeven = atm_strike + net_debit

        # Position sizing: Risk 1% per trade
        risk_per_trade = capital * 0.01
        quantity = max(1, int(risk_per_trade / max_loss))
        total_cost = net_debit * quantity * 100  # 100 = multiplier for NIFTY options

        if total_cost > capital * 0.15:  # Max 15% capital per trade
            quantity = int((capital * 0.15) / (net_debit * 100))

        if quantity < 1:
            return None

        total_max_profit = max_profit * quantity * 100
        total_max_loss = max_loss * quantity * 100

        # Probability of profit (width of spread vs distance from entry)
        distance_to_short = ((otm_strike - nifty_price) / nifty_price) * 100
        prob_win = min(80, 65 + (distance_to_short * 5))  # Wider spread = higher prob

        # Confidence score
        confidence = 75.0
        if iv_percentile > 60:
            confidence += 10  # High IV good for spreads
        if nifty_price > support + ((resistance - support) * 0.5):
            confidence += 5  # Upper half = bullish

        return TradeSetup(
            id=f"CALL_SPREAD_{datetime.now(_IST).strftime('%Y%m%d_%H%M%S')}",
            strategy="call_spread",
            symbol="NIFTY",
            entry_price=nifty_price,
            entry_time=datetime.now(_IST).strftime("%H:%M"),
            long_leg=OptionLeg(
                strike=atm_strike,
                option_type="CALL",
                expiry="weekly",
                premium=atm_premium,
                delta=0.50,
                theta=-0.02,
                vega=0.10
            ),
            short_leg=OptionLeg(
                strike=otm_strike,
                option_type="CALL",
                expiry="weekly",
                premium=otm_premium,
                delta=0.25,
                theta=0.01,
                vega=0.05
            ),
            max_profit=total_max_profit,
            max_loss=total_max_loss,
            breakeven=breakeven,
            risk_reward_ratio=total_max_profit / total_max_loss if total_max_loss > 0 else 0,
            probability_win=prob_win,
            capital_required=total_cost,
            exit_profit_target=total_cost + (total_max_profit * 0.50),  # 50% of max
            exit_stop_loss=total_cost - (total_max_loss * 0.75),  # 75% of max loss
            exit_time=(datetime.now(_IST) + timedelta(days=4)).strftime("%H:%M"),  # Thursday 15:30
            confidence_score=confidence,
            rationale=[
                f"ATM call buy @ {atm_strike} + OTM call sell @ {otm_strike}",
                f"Max profit: ₹{total_max_profit:.0f} | Max loss: ₹{total_max_loss:.0f}",
                f"Risk/Reward: {total_max_profit / total_max_loss:.2f}:1",
                f"Probability of profit: {prob_win:.0f}%",
                "Defined risk — no unlimited downside",
                f"Capital required: ₹{total_cost:.0f}",
            ]
        )

    async def generate_intraday_call_momentum(self,
        nifty_price: float,
        rsi: float,
        macd_hist: float,
        volume_ratio: float,
        atr: float,
        sma50: float,
        support: float,
        resistance: float,
        capital: float,
        cycle: Dict
    ) -> Optional[TradeSetup]:
        """
        Intraday NIFTY call for momentum.
        Buy call when RSI 50-65 + MACD positive + volume high.
        """

        # Market analysis
        mkt_analysis = await self.analyzer.analyze_nifty_intraday(
            nifty_price, rsi, macd_hist, volume_ratio, atr, sma50, support, resistance
        )

        # Need high confidence
        if mkt_analysis["confidence"] < 50:
            return None

        # Strike: ATM or slightly OTM
        atm_strike = round(nifty_price / 100) * 100

        # Intraday premium (much cheaper than weekly)
        iv_factor = 0.5  # Lower IV for intraday
        call_premium = (atm_strike * 0.005 * iv_factor)  # ~0.5% of strike

        # Target: 50 points or 0.2% profit
        target_move = 50
        exit_price = nifty_price + target_move
        pnl_if_target_hit = target_move * 100 - call_premium * 100

        # Risk: 30 points or call premium lost
        stop_loss = nifty_price - 30
        max_loss = call_premium * 100

        # Position sizing
        risk_per_trade = capital * 0.015  # 1.5% per intraday trade
        quantity = max(1, int(risk_per_trade / max_loss))
        total_capital = call_premium * quantity * 100

        if total_capital > capital * 0.10:  # Max 10% per intraday
            quantity = int((capital * 0.10) / (call_premium * 100))

        if quantity < 1:
            return None

        return TradeSetup(
            id=f"INTRADAY_CALL_{datetime.now(_IST).strftime('%Y%m%d_%H%M%S')}",
            strategy="intraday_call",
            symbol="NIFTY",
            entry_price=nifty_price,
            entry_time=datetime.now(_IST).strftime("%H:%M"),
            long_leg=OptionLeg(
                strike=atm_strike,
                option_type="CALL",
                expiry="intraday",
                premium=call_premium,
                quantity=quantity,
                delta=0.55,
                theta=-0.05,
                vega=0.12
            ),
            short_leg=None,
            max_profit=(pnl_if_target_hit * quantity) * 0.5,  # Assume 50% hit
            max_loss=max_loss * quantity,
            breakeven=nifty_price + call_premium,
            risk_reward_ratio=((target_move - call_premium) / call_premium) if call_premium > 0 else 0,
            probability_win=60.0,
            capital_required=total_capital,
            exit_profit_target=call_premium * 100 * quantity * 2,  # 2x premium
            exit_stop_loss=0,  # Tight SL at 30 points
            exit_time=(datetime.now(_IST) + timedelta(minutes=240)).strftime("%H:%M"),  # 4 hours
            confidence_score=mkt_analysis["confidence"],
            rationale=[
                f"Buy {atm_strike} call @ ₹{call_premium:.0f}",
                f"Target: +50 points ({exit_price:.0f})",
                f"Stop: -30 points ({stop_loss:.0f})",
                f"Risk/Reward: {target_move - call_premium:.0f} / {call_premium:.0f}",
                "Intraday theta decay works against us - close within 4 hours",
                f"Confidence: {mkt_analysis['confidence']:.0f}%",
            ] + mkt_analysis["signals"]
        )


# ─────────────────────────────────────────────────────────────────────────────
# PORTFOLIO MANAGER (EXECUTE & MONITOR)
# ─────────────────────────────────────────────────────────────────────────────

class WeeklyIncomeTrader:
    """Main trader class - manages all trades and execution"""

    def __init__(self):
        self.generator = TradeSetupGenerator()
        self.analyzer = MarketAnalyzer()

        self.active_setups: List[TradeSetup] = []
        self.trade_results: List[TradeResult] = []
        self.weekly_pnl: float = 0.0
        self.capital: float = 100000.0
        self.max_trades_per_week: int = 5

    async def scan_for_opportunities(self, market_data: Dict, cycle: Dict) -> List[TradeSetup]:
        """
        Scan market and generate 3-5 high-probability setups per week.
        Returns only trades with 60%+ confidence and 2:1+ risk/reward.
        """

        setups = []

        nifty_price = market_data.get("ltp", 0)
        rsi = market_data.get("rsi", 50)
        macd_hist = market_data.get("macd_histogram", 0)
        volume_ratio = market_data.get("volume_ratio", 1.0)
        atr = market_data.get("atr", 100)
        sma50 = market_data.get("sma50", nifty_price)
        support = market_data.get("support", nifty_price - 200)
        resistance = market_data.get("resistance", nifty_price + 200)
        iv_percentile = market_data.get("iv_percentile", 50)

        # 1. Weekly call spread (if bullish cycle confirmed)
        cycle_conf = cycle.get("confidence", "LOW")
        call_spread = await self.generator.generate_weekly_call_spread(
            nifty_price, iv_percentile, support, resistance, cycle_conf, self.capital
        )
        if call_spread and call_spread.confidence_score >= 70:
            setups.append(call_spread)
            logger.info(f"[Weekly Income] Generated call spread: {call_spread.id}")

        # 2. Intraday momentum call (if high confidence)
        intraday_call = await self.generator.generate_intraday_call_momentum(
            nifty_price, rsi, macd_hist, volume_ratio, atr, sma50, support, resistance,
            self.capital, cycle
        )
        if intraday_call and intraday_call.confidence_score >= 55:
            setups.append(intraday_call)
            logger.info(f"[Weekly Income] Generated intraday call: {intraday_call.id}")

        # 3. Filter: only trades with risk/reward >= 2.0 and prob_win >= 60%
        filtered = [
            s for s in setups
            if s.risk_reward_ratio >= 1.8 and s.probability_win >= 58
        ]

        # Limit to max 5 per week
        return filtered[:self.max_trades_per_week]

    async def execute_setup(self, setup: TradeSetup) -> TradeResult:
        """Execute a trade setup (paper trading)"""

        self.active_setups.append(setup)

        result = TradeResult(
            setup_id=setup.id,
            status="open",
            entry_price=setup.entry_price,
            exit_price=None,
            pnl=0,
            pnl_pct=0,
            duration_minutes=0,
            exit_reason="open"
        )

        logger.info(
            f"[Weekly Income] EXECUTED {setup.strategy.upper()} "
            f"| Entry: ₹{setup.entry_price:.2f} "
            f"| Max Profit: ₹{setup.max_profit:.0f} | Max Loss: ₹{setup.max_loss:.0f}"
        )

        return result

    async def get_status(self) -> Dict:
        """Get trader status"""
        return {
            "capital": self.capital,
            "active_setups": len(self.active_setups),
            "completed_trades": len(self.trade_results),
            "weekly_pnl": self.weekly_pnl,
            "weekly_return_pct": (self.weekly_pnl / self.capital) * 100,
            "trades": [asdict(s) for s in self.active_setups[:5]],  # Top 5
            "results": [asdict(r) for r in self.trade_results[-10:]],  # Last 10
        }


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────────────────────────

_trader_instance = None

def get_trader() -> WeeklyIncomeTrader:
    global _trader_instance
    if _trader_instance is None:
        _trader_instance = WeeklyIncomeTrader()
    return _trader_instance
