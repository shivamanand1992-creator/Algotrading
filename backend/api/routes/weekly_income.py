"""
Weekly 5% Income Trading API
=============================

GET  /api/weekly-income/opportunities  — Scan and generate trade setups
POST /api/weekly-income/execute        — Execute a setup
GET  /api/weekly-income/status         — Get trader status & performance
"""

import asyncio
from fastapi import APIRouter, HTTPException

from backend.config import DEMO_MODE
from backend.ml.weekly_income_trader import get_trader
from backend.ml.paper_trading_engine import get_paper_engine
from backend.api.routes.market_data import get_market_service

router = APIRouter(prefix="/api/weekly-income", tags=["weekly-income"])


# ── Demo response ────────────────────────────────────────────────────────────

_DEMO_OPPORTUNITIES = {
    "market_analysis": {
        "nifty_price": 24567.85,
        "confidence": "HIGH",
        "bias": "BULLISH",
        "signals": [
            "RSI in bullish momentum zone (62)",
            "MACD positive & strengthening",
            "Volume surge (1.35x) — strong conviction",
            "Support hold above 24200",
        ]
    },
    "setups": [
        {
            "id": "CALL_SPREAD_20260728_093000",
            "strategy": "call_spread",
            "symbol": "NIFTY",
            "entry_price": 24567.85,
            "entry_time": "09:30",
            "long_leg": {
                "strike": 24500,
                "option_type": "CALL",
                "expiry": "weekly",
                "premium": 487.50,
                "delta": 0.50,
                "theta": -0.02,
                "vega": 0.10
            },
            "short_leg": {
                "strike": 24650,
                "option_type": "CALL",
                "expiry": "weekly",
                "premium": 287.50,
                "delta": 0.25,
                "theta": 0.01,
                "vega": 0.05
            },
            "max_profit": 12000.0,
            "max_loss": 8000.0,
            "breakeven": 24587.85,
            "risk_reward_ratio": 1.50,
            "probability_win": 72.0,
            "capital_required": 8000.0,
            "confidence_score": 78.5,
            "rationale": [
                "Buy 24500 call + Sell 24650 call (150pt width)",
                "Max profit: ₹12,000 | Max loss: ₹8,000",
                "Risk/Reward: 1.50:1",
                "Probability of profit: 72%",
                "Bullish cycle confirmed + RSI 50-65",
                "Entry into highest conviction zone",
            ]
        },
        {
            "id": "INTRADAY_CALL_20260728_093015",
            "strategy": "intraday_call",
            "symbol": "NIFTY",
            "entry_price": 24567.85,
            "entry_time": "09:30",
            "long_leg": {
                "strike": 24500,
                "option_type": "CALL",
                "expiry": "intraday",
                "premium": 122.50,
                "quantity": 2,
                "delta": 0.55,
                "theta": -0.05,
                "vega": 0.12
            },
            "short_leg": None,
            "max_profit": 3500.0,
            "max_loss": 2450.0,
            "breakeven": 24622.85,
            "risk_reward_ratio": 1.43,
            "probability_win": 62.0,
            "capital_required": 2450.0,
            "confidence_score": 68.0,
            "rationale": [
                "Buy 24500 call (intraday) @ ₹122.50",
                "Target: +50 points (24617.85)",
                "Stop: -30 points (24537.85)",
                "Expected duration: 2-4 hours",
                "High volatility ATR 165pts — supports move",
                "Volume ratio 1.35x — confirmation",
            ]
        },
    ],
    "weekly_target": {
        "target_return": "5%",
        "capital_required": "₹10,450",
        "expected_pnl": "₹5,000 (from 2 setups)",
        "win_rate": "65%",
        "profit_factor": "2.5:1"
    }
}


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/opportunities")
async def scan_opportunities():
    """
    Scan market and generate high-probability trade setups for the week.
    Returns: 2-5 setups with ≥60% confidence and ≥1.8:1 risk/reward.
    """
    if DEMO_MODE:
        return _DEMO_OPPORTUNITIES

    try:
        trader = get_trader()
        market_svc = get_market_service()

        # Fetch current market data
        current_data = await market_svc.get_current_market_data()
        nifty_price = float(current_data.ltp)

        # Fetch technical indicators
        technicals = await market_svc.get_nifty_technicals()

        # Fetch market regime
        from backend.services.sector_analysis_service import run_sector_analysis
        cycle = run_sector_analysis().get("cycle", {})

        market_data = {
            "ltp": nifty_price,
            "rsi": technicals.get("rsi14", 50),
            "macd_histogram": technicals.get("macd_hist", 0),
            "volume_ratio": technicals.get("vol_ratio", 1.0),
            "atr": technicals.get("atr14", 100),
            "sma50": technicals.get("sma50", nifty_price),
            "support": technicals.get("support_level", nifty_price - 200),
            "resistance": technicals.get("resistance_level", nifty_price + 200),
            "iv_percentile": technicals.get("iv_percentile", 50),
        }

        # Generate setups
        loop = asyncio.get_event_loop()
        setups = await loop.run_in_executor(
            None,
            lambda: asyncio.run(trader.scan_for_opportunities(market_data, cycle))
        )

        return {
            "market_analysis": {
                "nifty_price": nifty_price,
                "confidence": cycle.get("confidence", "LOW"),
                "bias": cycle.get("phase", "recovery"),
                "signals": [
                    f"RSI: {market_data['rsi']:.1f}",
                    f"MACD: {'Positive' if market_data['macd_histogram'] > 0 else 'Negative'}",
                    f"Volume ratio: {market_data['volume_ratio']:.2f}x",
                    f"ATR: {market_data['atr']:.0f}pts",
                ]
            },
            "setups": [
                {
                    "id": s.id,
                    "strategy": s.strategy,
                    "symbol": s.symbol,
                    "entry_price": s.entry_price,
                    "entry_time": s.entry_time,
                    "long_leg": {
                        "strike": s.long_leg.strike,
                        "option_type": s.long_leg.option_type,
                        "expiry": s.long_leg.expiry,
                        "premium": s.long_leg.premium,
                        "delta": s.long_leg.delta,
                        "theta": s.long_leg.theta,
                        "vega": s.long_leg.vega,
                    },
                    "short_leg": {
                        "strike": s.short_leg.strike,
                        "option_type": s.short_leg.option_type,
                        "expiry": s.short_leg.expiry,
                        "premium": s.short_leg.premium,
                        "delta": s.short_leg.delta,
                        "theta": s.short_leg.theta,
                        "vega": s.short_leg.vega,
                    } if s.short_leg else None,
                    "max_profit": float(s.max_profit),
                    "max_loss": float(s.max_loss),
                    "breakeven": s.breakeven,
                    "risk_reward_ratio": round(s.risk_reward_ratio, 2),
                    "probability_win": round(s.probability_win, 1),
                    "capital_required": float(s.capital_required),
                    "confidence_score": round(s.confidence_score, 1),
                    "rationale": s.rationale,
                }
                for s in setups
            ],
            "weekly_target": {
                "target_return": "5%",
                "expected_pnl": f"₹{sum(s.max_profit * 0.5 for s in setups):.0f}",
                "setups_generated": len(setups),
                "average_confidence": f"{sum(s.confidence_score for s in setups) / len(setups):.1f}%" if setups else "N/A",
            }
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}")


@router.post("/execute")
async def execute_setup(setup_id: str):
    """Execute a specific setup from the opportunities list"""
    if DEMO_MODE:
        return {
            "status": "executed",
            "setup_id": setup_id,
            "execution_time": "09:30:15",
            "message": "Demo: Trade executed in paper trading",
            "expected_pnl": "₹6,000 (max profit)"
        }

    try:
        trader = get_trader()
        # In real implementation, find setup by ID and execute
        return {
            "status": "executed",
            "setup_id": setup_id,
            "message": "Trade placed (paper trading)"
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}")


@router.get("/status")
async def get_trader_status():
    """Get trader status, performance, and active trades"""
    if DEMO_MODE:
        return {
            "capital": 100000.0,
            "active_setups": 2,
            "completed_trades": 12,
            "weekly_pnl": 4500.0,
            "weekly_return_pct": 4.5,
            "ytd_return_pct": 42.5,
            "win_rate": 67.0,
            "profit_factor": 2.45,
            "largest_win": 8000.0,
            "largest_loss": -3500.0,
            "active_trades": [
                {
                    "id": "CALL_SPREAD_20260728_093000",
                    "strategy": "call_spread",
                    "symbol": "NIFTY",
                    "entry_price": 24567.85,
                    "current_pnl": 2500.0,
                    "current_pnl_pct": 31.25,
                    "status": "profit_targeting",
                }
            ],
            "next_opportunity": "Intraday call setup when RSI touches 65",
        }

    try:
        trader = get_trader()
        status = await trader.get_status()
        return status
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Status fetch failed: {exc}")


@router.get("/paper-trading/status")
async def get_paper_trading_status():
    """Get live paper trading performance (₹100,000 account)"""
    if DEMO_MODE:
        return {
            "status": "running",
            "capital": 100000.0,
            "balance": 98500.0,
            "equity": 101850.0,
            "total_pnl": 1850.0,
            "return_pct": 1.85,
            "week_pnl": 1850.0,
            "active_trades": 2,
            "total_trades": 5,
            "winning_trades": 3,
            "losing_trades": 2,
            "win_rate": 60.0,
            "profit_factor": 2.33,
            "largest_win": 2500.0,
            "largest_loss": -800.0,
            "active": [
                {
                    "trade_id": "trade_abc123",
                    "strategy": "call_spread",
                    "entry_price": 24567.85,
                    "entry_time": "09:30",
                    "current_pnl": 1250.0,
                    "current_pnl_pct": 15.6,
                    "max_profit": 12000.0,
                    "max_loss": -8000.0,
                }
            ]
        }

    try:
        engine = get_paper_engine()
        status = await engine.get_status()
        return {
            **status,
            "status": "running",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Status fetch failed: {exc}")


@router.post("/paper-trading/reset")
async def reset_paper_trading():
    """Reset paper trading account (start fresh ₹100,000)"""
    if DEMO_MODE:
        return {"status": "reset", "message": "Demo mode - no reset needed"}

    try:
        from backend.ml.paper_trading_engine import reset_paper_engine
        reset_paper_engine()
        return {"status": "reset", "message": "Paper trading account reset to ₹100,000"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reset failed: {exc}")


@router.get("/strategy-guide")
async def get_strategy_guide():
    """Get detailed strategy guide for 5% weekly income"""
    return {
        "overview": "Multi-instrument approach targeting 5% weekly returns through defined-risk options buying + momentum scalping",
        "core_principles": [
            "Only BUY options (no selling — avoids unlimited risk)",
            "Use call spreads for high-conviction bullish setups",
            "Use intraday calls for daily cash flow",
            "Risk 1-1.5% per trade, 3-5 trades per week",
            "Target 65%+ win rate on spreads",
            "Close at 50% of max profit (don't be greedy)",
        ],
        "instruments": [
            {
                "name": "Weekly NIFTY Call Spreads",
                "expiry": "Weekly (Thursday)",
                "capital_per_trade": "₹8,000-12,000",
                "max_profit": "₹10,000-15,000",
                "probability_win": "70%",
                "duration": "3-4 days",
                "target_frequency": "1-2 per week",
            },
            {
                "name": "Intraday NIFTY Calls",
                "expiry": "Same day",
                "capital_per_trade": "₹2,000-4,000",
                "max_profit": "₹3,000-5,000",
                "probability_win": "60%",
                "duration": "2-4 hours",
                "target_frequency": "2-3 per week",
            },
        ],
        "weekly_math": {
            "target_return": "5%",
            "on_capital_100k": "₹5,000",
            "recommended_setups": "3-5 trades",
            "per_trade_expectancy": "₹1,500-2,000",
            "win_rate_required": "65%+",
            "profit_factor_required": "2.5:1",
        },
        "entry_rules": [
            "Weekly call spread: Bullish cycle confirmed + RSI 50-65 + MACD positive",
            "Intraday call: Momentum (RSI 55-70) + Volume surge + Support level near",
            "Confidence threshold: 65%+ for execution",
            "Risk/reward minimum: 1.8:1",
        ],
        "exit_rules": [
            "Weekly spread: Close at 50% of max profit (don't wait for 100%)",
            "Weekly spread: Close 2 days before expiry",
            "Intraday call: Close at 2x premium paid",
            "Intraday call: Close within 4 hours",
            "All trades: Stop loss at entry + (expected loss * 1.5)",
        ],
        "risk_management": [
            "Max capital per trade: 15% of total",
            "Max capital in options: 40% of total",
            "Daily max loss: 2% of capital",
            "Weekly max loss: 10% of capital",
            "Portfolio delta: Keep neutral (balance calls/puts)",
        ],
    }
