from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict

from backend.api.models.responses import StrategyStatus, TradeSignalResponse
from backend.api.models.requests import StartStrategyRequest, UpdateStrategyConfigRequest
from backend.dependencies import get_order_manager, get_signal_generator
from backend.services.strategy_service import StrategyService
from backend.config import config, DEMO_MODE

router = APIRouter(prefix="/api/strategies", tags=["strategies"])

# Global strategy service instance
_strategy_service = None


def get_strategy_service():
    global _strategy_service
    if _strategy_service is None:
        order_manager = get_order_manager()
        signal_generator = get_signal_generator()
        _strategy_service = StrategyService(
            config.trading_config,
            order_manager,
            signal_generator
        )
    return _strategy_service


_DEMO_STRATEGIES = [
    StrategyStatus(name="trend", display_name="Trend Following", status="stopped",
                   mode="paper", uptime_seconds=0, signals_today=3, trades_today=2,
                   pnl_today=840.0, regime_suitable=True),
    StrategyStatus(name="premium", display_name="Premium Selling", status="stopped",
                   mode="paper", uptime_seconds=0, signals_today=1, trades_today=1,
                   pnl_today=-577.5, regime_suitable=False),
    StrategyStatus(name="scalping", display_name="Scalping", status="stopped",
                   mode="paper", uptime_seconds=0, signals_today=7, trades_today=4,
                   pnl_today=320.0, regime_suitable=True),
]


@router.get("", response_model=List[StrategyStatus])
async def list_strategies(service: StrategyService = Depends(get_strategy_service)):
    """List all available strategies with their status"""
    if DEMO_MODE:
        return _DEMO_STRATEGIES
    return await service.get_all_strategies()


@router.post("/{name}/start")
async def start_strategy(
    name: str,
    request: StartStrategyRequest,
    service: StrategyService = Depends(get_strategy_service)
):
    """Start a strategy"""
    try:
        success = await service.start_strategy(name, request.mode)
        return {
            "success": success,
            "message": f"Strategy {name} started in {request.mode} mode"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{name}/stop")
async def stop_strategy(
    name: str,
    service: StrategyService = Depends(get_strategy_service)
):
    """Stop a running strategy"""
    try:
        success = await service.stop_strategy(name)
        return {
            "success": success,
            "message": f"Strategy {name} stopped"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{name}/config", response_model=Dict)
async def get_strategy_config(
    name: str,
    service: StrategyService = Depends(get_strategy_service)
):
    """Get strategy configuration"""
    try:
        config_data = await service.get_strategy_config(name)
        return config_data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{name}/config")
async def update_strategy_config(
    name: str,
    request: UpdateStrategyConfigRequest,
    service: StrategyService = Depends(get_strategy_service)
):
    """Update strategy configuration"""
    try:
        success = await service.update_strategy_config(name, request.config)
        return {
            "success": success,
            "message": f"Strategy {name} configuration updated"
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{name}/signals", response_model=List[TradeSignalResponse])
async def get_strategy_signals(
    name: str,
    limit: int = 20,
    service: StrategyService = Depends(get_strategy_service)
):
    """Get recent signals from a strategy"""
    return await service.get_strategy_signals(name, limit)
