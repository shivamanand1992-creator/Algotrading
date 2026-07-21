"""
ML-Powered Intraday Trading API Routes
Expectancy-optimized stock scoring and signal generation
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List, Optional
from pydantic import BaseModel
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ml-intraday", tags=["ML Intraday Trading"])


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class StockScore(BaseModel):
    """Individual stock score breakdown"""
    symbol: str
    score: int  # 0-100
    price: float
    features: Dict[str, int]  # trend, momentum, volume, pattern scores
    timestamp: str


class Signal(BaseModel):
    """Trading signal with full details"""
    symbol: str
    score: int
    probability: float  # P(success) from ML model
    entry: float
    stop_loss: float
    target: float
    reward_risk: float
    hold_time: int  # minutes
    features: Dict[str, int]
    reasoning: Optional[str] = None


class SystemStatus(BaseModel):
    """ML system health status"""
    model_loaded: bool
    last_update: Optional[str]
    stocks_tracked: int
    features_calculated: int
    signals_active: int


class ExplanationRequest(BaseModel):
    """Request for AI explanation of signal"""
    symbol: str
    score: int
    features: Dict[str, int]


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================

def get_ml_service():
    """Get ML intraday service singleton"""
    # TODO: Implement ML service singleton pattern
    # from backend.services.ml_intraday_service import MLIntradayService
    # return MLIntradayService.get_instance()
    return None


# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.get("/status", response_model=SystemStatus)
async def get_system_status():
    """
    Get ML system status and health metrics

    Returns:
        SystemStatus with model state, last update, stocks tracked
    """
    try:
        # TODO: Get from actual ML service
        return SystemStatus(
            model_loaded=False,  # Will be True once models are trained
            last_update=None,
            stocks_tracked=0,
            features_calculated=0,
            signals_active=0
        )
    except Exception as e:
        logger.error(f"[ML Intraday] Failed to get system status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-stocks")
async def get_top_stocks():
    """
    Get top-scored stocks from ML models

    Returns:
        {
            "stocks": [StockScore],
            "signals": [Signal] (only for score >= 90)
        }
    """
    try:
        # TODO: Get from actual ML service
        # service = get_ml_service()
        # scores = service.get_latest_scores()
        # signals = service.get_active_signals()

        # Demo data for now
        demo_stocks = [
            {
                "symbol": "RELIANCE",
                "score": 92,
                "price": 2850.50,
                "features": {
                    "trend": 95,
                    "momentum": 91,
                    "volume": 88,
                    "pattern": 89
                },
                "timestamp": datetime.now().isoformat()
            },
            {
                "symbol": "INFY",
                "score": 88,
                "price": 1520.30,
                "features": {
                    "trend": 90,
                    "momentum": 85,
                    "volume": 82,
                    "pattern": 91
                },
                "timestamp": datetime.now().isoformat()
            },
            {
                "symbol": "TCS",
                "score": 85,
                "price": 3420.75,
                "features": {
                    "trend": 88,
                    "momentum": 80,
                    "volume": 78,
                    "pattern": 87
                },
                "timestamp": datetime.now().isoformat()
            }
        ]

        demo_signals = [
            {
                "symbol": "RELIANCE",
                "score": 92,
                "probability": 74.5,
                "entry": 2850.50,
                "stop_loss": 2835.00,
                "target": 2885.00,
                "reward_risk": 2.2,
                "hold_time": 40,
                "features": {
                    "trend": 95,
                    "momentum": 91,
                    "volume": 88,
                    "pattern": 89
                }
            }
        ]

        return {
            "stocks": demo_stocks,
            "signals": demo_signals
        }

    except Exception as e:
        logger.error(f"[ML Intraday] Failed to get top stocks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/explain")
async def explain_signal(request: ExplanationRequest):
    """
    Get AI-generated explanation for why a stock scored high

    Uses Claude to explain the ML model's decision (not to make the decision)

    Args:
        request: ExplanationRequest with symbol, score, features

    Returns:
        {"explanation": str} - Human-readable explanation
    """
    try:
        # TODO: Call Claude API for explanation
        # from backend.services.ml_explanation_service import generate_explanation
        # explanation = await generate_explanation(request.symbol, request.score, request.features)

        # Demo explanation for now
        explanation = f"""
{request.symbol} (Score: {request.score}/100) - STRONG BUY

Why this signal is strong:
• Trend ({request.features.get('trend', 0)}/100): Price above EMA20/50/200, all EMAs aligned upward
• Momentum ({request.features.get('momentum', 0)}/100): RSI at 62 (healthy), ADX showing strong trend
• Volume ({request.features.get('volume', 0)}/100): Current volume 1.8x average, institutional buying
• Pattern ({request.features.get('pattern', 0)}/100): Breakout above previous day high

Technical Setup:
• Entry: Current market price (breakout level)
• Stop Loss: Below consolidation zone
• Target: Previous resistance level
• Risk:Reward = 2.2:1

Expected Hold: 40 minutes
Probability of Success: 74% (based on 6 months walk-forward backtest)

Model Confidence: HIGH
This setup matches 847 historical instances where 74% reached target before stop-loss.
Average win: +1.2%, Average loss: -0.55%
Expected value per trade: +0.65%
"""

        return {"explanation": explanation}

    except Exception as e:
        logger.error(f"[ML Intraday] Failed to generate explanation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backtest-results")
async def get_backtest_results():
    """
    Get latest walk-forward backtest performance metrics

    Returns:
        {
            "period": "2024-01-01 to 2024-07-21",
            "total_trades": int,
            "win_rate": float,
            "avg_win": float,
            "avg_loss": float,
            "expectancy": float,
            "total_pnl": float,
            "max_drawdown": float
        }
    """
    try:
        # TODO: Get from actual backtest results
        return {
            "period": "Demo Mode - No backtest yet",
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "expectancy": 0.0,
            "total_pnl": 0.0,
            "max_drawdown": 0.0,
            "message": "Run backtest first: python backend/ml/run_backtest.py"
        }

    except Exception as e:
        logger.error(f"[ML Intraday] Failed to get backtest results: {e}")
        raise HTTPException(status_code=500, detail=str(e))
