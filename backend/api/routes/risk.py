from fastapi import APIRouter, Depends
from typing import List

from backend.api.models.responses import RiskLimitsResponse, RiskMetricsResponse, RiskAlert
from backend.dependencies import get_risk_manager, get_position_manager
from backend.config import config

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/limits", response_model=RiskLimitsResponse)
async def get_risk_limits(
    risk_manager=Depends(get_risk_manager),
    position_manager=Depends(get_position_manager)
):
    """Get current risk limits vs usage"""
    # Get config limits
    risk_config = config.trading_config.get('risk_management', {})
    daily_loss_limit = risk_config.get('daily_loss_limit', 20000)
    per_trade_risk = risk_config.get('per_trade_risk_percent', 1.0)
    max_positions = risk_config.get('max_positions', 5)

    # Calculate current usage
    # TODO: Get actual daily P&L from risk manager
    daily_loss_used = 0
    daily_loss_pct = (daily_loss_used / daily_loss_limit * 100) if daily_loss_limit > 0 else 0

    current_positions = len(position_manager.get_all_positions())

    return RiskLimitsResponse(
        daily_loss_limit=daily_loss_limit,
        daily_loss_used=daily_loss_used,
        daily_loss_percentage=daily_loss_pct,
        per_trade_risk_limit=per_trade_risk,
        max_positions=max_positions,
        current_positions=current_positions
    )


@router.get("/metrics", response_model=RiskMetricsResponse)
async def get_risk_metrics():
    """Get risk metrics (VaR, max drawdown, etc.)"""
    # TODO: Calculate from historical data
    return RiskMetricsResponse(
        var_95=5000.0,
        var_99=10000.0,
        max_drawdown=0.0,
        position_concentration=0.0,
        leverage=1.0
    )


@router.get("/alerts", response_model=List[RiskAlert])
async def get_risk_alerts():
    """Get active risk alerts"""
    # TODO: Check for risk violations
    return []
