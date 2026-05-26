from fastapi import APIRouter, Depends
from typing import List

from backend.api.models.responses import RiskLimitsResponse, RiskMetricsResponse, RiskAlert
from backend.api.models.requests import UpdateRiskLimitsRequest
from backend.dependencies import get_risk_manager, get_position_manager
from backend.config import config, DEMO_MODE

router = APIRouter(prefix="/api/risk", tags=["risk"])

# Runtime overrides — take precedence over config.yaml values
_risk_overrides: dict = {}


@router.get("/limits", response_model=RiskLimitsResponse)
async def get_risk_limits(
    risk_manager=Depends(get_risk_manager),
    position_manager=Depends(get_position_manager)
):
    if DEMO_MODE:
        daily_limit = _risk_overrides.get('daily_loss_limit', 20000)
        max_pos = _risk_overrides.get('max_positions', 5)
        per_trade = _risk_overrides.get('per_trade_risk_percent', 1.0)
        return RiskLimitsResponse(
            daily_loss_limit=daily_limit, daily_loss_used=577.5,
            daily_loss_percentage=round(577.5 / daily_limit * 100, 2),
            per_trade_risk_limit=per_trade, max_positions=max_pos, current_positions=2
        )
    """Get current risk limits vs usage"""
    risk_config = config.trading_config.get('risk_management', {})
    daily_loss_limit = _risk_overrides.get(
        'daily_loss_limit', risk_config.get('daily_loss_limit', 20000)
    )
    per_trade_risk = _risk_overrides.get(
        'per_trade_risk_percent', risk_config.get('per_trade_risk_percent', 1.0)
    )
    max_positions = _risk_overrides.get(
        'max_positions', risk_config.get('max_positions', 5)
    )

    daily_loss_used = 0
    if risk_manager:
        try:
            status = risk_manager.get_risk_status()
            daily_loss_used = abs(min(0.0, status.get('daily_pnl', 0.0)))
        except Exception:
            pass

    daily_loss_pct = (daily_loss_used / daily_loss_limit * 100) if daily_loss_limit > 0 else 0
    current_positions = len(position_manager.get_open_positions()) if position_manager else 0

    return RiskLimitsResponse(
        daily_loss_limit=daily_loss_limit,
        daily_loss_used=daily_loss_used,
        daily_loss_percentage=daily_loss_pct,
        per_trade_risk_limit=per_trade_risk,
        max_positions=max_positions,
        current_positions=current_positions
    )


@router.put("/limits")
async def update_risk_limits(
    body: UpdateRiskLimitsRequest,
    risk_manager=Depends(get_risk_manager),
):
    """Update risk limits at runtime. Changes take effect immediately."""
    updated = []

    if body.daily_loss_limit is not None and body.daily_loss_limit > 0:
        _risk_overrides['daily_loss_limit'] = body.daily_loss_limit
        # Also update the live risk manager instance so it enforces the new limit
        if risk_manager:
            risk_manager.daily_loss_limit = body.daily_loss_limit
        updated.append(f"daily_loss_limit=₹{body.daily_loss_limit:,.0f}")

    if body.max_positions is not None and body.max_positions > 0:
        _risk_overrides['max_positions'] = body.max_positions
        updated.append(f"max_positions={body.max_positions}")

    if body.per_trade_risk_percent is not None and body.per_trade_risk_percent > 0:
        _risk_overrides['per_trade_risk_percent'] = body.per_trade_risk_percent
        updated.append(f"per_trade_risk={body.per_trade_risk_percent}%")

    return {
        "success": True,
        "updated": updated,
        "message": f"Updated: {', '.join(updated)}" if updated else "No changes made",
    }


@router.get("/metrics", response_model=RiskMetricsResponse)
async def get_risk_metrics():
    """Get risk metrics (VaR, max drawdown, etc.)"""
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
    return []
