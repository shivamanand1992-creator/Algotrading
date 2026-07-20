"""
Athena Options Trading API Routes
AI-powered weekly options trading with 80% target success rate
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from backend.services.athena_options_service import AthenaOptionsService
from backend.dependencies import get_angel_client
from loguru import logger

router = APIRouter(prefix="/api/athena", tags=["Athena Options"])

# Dependency to get service instance
_service_instance: Optional[AthenaOptionsService] = None


def get_athena_service() -> AthenaOptionsService:
    """Get or create Athena service singleton"""
    global _service_instance

    if _service_instance is None:
        try:
            angel_client = get_angel_client()
            _service_instance = AthenaOptionsService(angel_client)
            logger.info("[Athena API] Service initialized")
        except Exception as e:
            logger.error(f"[Athena API] Failed to initialize service: {e}")
            raise HTTPException(status_code=500, detail="Athena service initialization failed")

    return _service_instance


# Request/Response Models
class EnableAthenaRequest(BaseModel):
    mode: str = "paper"  # 'paper' or 'live'


class AthenaStatusResponse(BaseModel):
    enabled: bool
    mode: str
    positions: int
    trades_this_week: int
    weekly_pnl: float
    max_positions: int
    min_confidence: float
    min_pop: float


class PositionResponse(BaseModel):
    id: Optional[int]
    strategy: str
    symbol: str
    entry_date: datetime
    expiry_date: Optional[datetime]
    strikes: dict
    premium_received: float
    max_loss: float
    current_value: float
    realized_pnl: float
    confidence: float
    probability_of_profit: float
    exit_date: Optional[datetime]
    exit_reason: Optional[str]
    status: str
    mode: str
    reasoning: Optional[str]


class AnalysisResponse(BaseModel):
    action: str
    strategy: Optional[str]
    confidence: Optional[float]
    details: Optional[dict]
    reason: Optional[str]


@router.post("/enable")
async def enable_athena(
    request: EnableAthenaRequest,
    service: AthenaOptionsService = Depends(get_athena_service)
):
    """
    Enable Athena options trading

    Args:
        mode: 'paper' (simulation) or 'live' (real trading)
    """
    if request.mode not in ['paper', 'live']:
        raise HTTPException(status_code=400, detail="Mode must be 'paper' or 'live'")

    service.enable(mode=request.mode)

    return {
        "status": "success",
        "message": f"Athena enabled in {request.mode.upper()} mode",
        "config": service.get_status()
    }


@router.post("/disable")
async def disable_athena(
    service: AthenaOptionsService = Depends(get_athena_service)
):
    """Disable Athena options trading"""
    service.disable()

    return {
        "status": "success",
        "message": "Athena disabled",
        "config": service.get_status()
    }


@router.get("/status", response_model=AthenaStatusResponse)
async def get_status(
    service: AthenaOptionsService = Depends(get_athena_service)
):
    """Get current Athena status and configuration"""
    return service.get_status()


@router.get("/positions")
async def get_positions(
    service: AthenaOptionsService = Depends(get_athena_service)
) -> List[dict]:
    """Get all active options positions"""
    return service.positions


@router.post("/analyze", response_model=AnalysisResponse)
async def run_analysis(
    service: AthenaOptionsService = Depends(get_athena_service)
):
    """
    Trigger manual options analysis

    Returns AI recommendation for current market conditions
    """
    try:
        result = await service.run_analysis_cycle()
        return result
    except Exception as e:
        logger.error(f"[Athena API] Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/monitor")
async def monitor_positions(
    service: AthenaOptionsService = Depends(get_athena_service)
):
    """
    Monitor open positions and exit if target/stop hit

    Returns list of position updates
    """
    try:
        updates = await service.monitor_positions()
        return {
            "status": "success",
            "updates": updates,
            "positions_checked": len(service.positions)
        }
    except Exception as e:
        logger.error(f"[Athena API] Position monitoring failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_config(
    service: AthenaOptionsService = Depends(get_athena_service)
):
    """Get Athena configuration"""
    return service.config


@router.patch("/config")
async def update_config(
    updates: dict,
    service: AthenaOptionsService = Depends(get_athena_service)
):
    """
    Update Athena configuration

    Example:
        {
            "min_confidence": 0.85,
            "min_pop": 0.80,
            "profit_target_pct": 60
        }
    """
    allowed_keys = {
        'max_positions', 'capital_per_trade', 'profit_target_pct',
        'stop_loss_pct', 'min_confidence', 'min_pop'
    }

    for key, value in updates.items():
        if key in allowed_keys:
            service.config[key] = value
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid config key: {key}. Allowed: {allowed_keys}"
            )

    return {
        "status": "success",
        "message": "Configuration updated",
        "config": service.config
    }
