from fastapi import APIRouter, Depends, HTTPException
from typing import List

from backend.api.models.responses import PositionResponse, PortfolioSummary
from backend.api.models.requests import ClosePositionRequest
from backend.dependencies import get_position_manager
from backend.services.position_service import PositionService
from backend.config import config, DEMO_MODE

router = APIRouter(prefix="/api", tags=["positions"])

# Global position service instance
_position_service = None


def get_position_service():
    global _position_service
    if _position_service is None:
        position_manager = get_position_manager()
        _position_service = PositionService(position_manager, config.trading_config)
    return _position_service


@router.get("/positions", response_model=List[PositionResponse])
async def get_all_positions(service: PositionService = Depends(get_position_service)):
    """Get all open positions"""
    if DEMO_MODE:
        return [
            PositionResponse(order_id="DEMO001", symbol="NIFTY25MAY24500CE", strike=24500,
                             entry_price=145.50, current_price=162.30, qty=50,
                             direction="BUY", unrealized_pnl=840.0, realized_pnl=0.0,
                             pnl_percentage=11.55, strategy="trend", regime="trending_up",
                             sl_price=130.0, target_price=180.0,
                             entry_time="2024-05-25T09:30:00"),
            PositionResponse(order_id="DEMO002", symbol="NIFTY25MAY24400PE", strike=24400,
                             entry_price=98.75, current_price=87.20, qty=50,
                             direction="BUY", unrealized_pnl=-577.5, realized_pnl=0.0,
                             pnl_percentage=-11.69, strategy="premium", regime="trending_up",
                             sl_price=88.0, target_price=120.0,
                             entry_time="2024-05-25T10:15:00"),
        ]
    return await service.get_all_positions()


@router.get("/positions/{order_id}", response_model=PositionResponse)
async def get_position(
    order_id: str,
    service: PositionService = Depends(get_position_service)
):
    """Get specific position details"""
    position = await service.get_position(order_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return position


@router.post("/positions/{order_id}/close")
async def close_position(
    order_id: str,
    request: ClosePositionRequest,
    service: PositionService = Depends(get_position_service)
):
    """Manually close a position"""
    try:
        success = await service.close_position(order_id, request.reason)
        return {
            "success": success,
            "message": f"Position {order_id} closed"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/portfolio/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(service: PositionService = Depends(get_position_service)):
    """Get portfolio summary"""
    if DEMO_MODE:
        return PortfolioSummary(
            total_capital=500000.0, used_capital=121250.0, available_capital=378750.0,
            total_pnl=262.5, total_pnl_percentage=0.05,
            open_positions_count=2, daily_pnl=262.5, daily_pnl_percentage=0.05
        )
    return await service.get_portfolio_summary()
