from fastapi import APIRouter, Depends, HTTPException
from typing import List

from backend.api.models.responses import PositionResponse, PortfolioSummary
from backend.api.models.requests import ClosePositionRequest
from backend.dependencies import get_position_manager
from backend.services.position_service import PositionService
from backend.config import config

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
    return await service.get_portfolio_summary()
