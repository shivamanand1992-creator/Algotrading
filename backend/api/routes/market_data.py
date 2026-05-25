from fastapi import APIRouter, Depends
from typing import List

from backend.api.models.responses import (
    MarketDataResponse,
    OptionsChainItem,
    MarketRegimeResponse,
    PredictionResponse
)
from backend.dependencies import (
    get_angel_client,
    get_options_analyzer,
    get_signal_generator
)
from backend.services.market_service import MarketService
from backend.config import config

router = APIRouter(prefix="/api/market", tags=["market"])

# Global market service instance
_market_service = None


def get_market_service():
    global _market_service
    if _market_service is None:
        angel_client = get_angel_client()
        options_analyzer = get_options_analyzer()
        signal_generator = get_signal_generator()
        _market_service = MarketService(
            angel_client,
            options_analyzer,
            signal_generator,
            config.trading_config
        )
    return _market_service


@router.get("/current", response_model=MarketDataResponse)
async def get_current_market_data(service: MarketService = Depends(get_market_service)):
    """Get current market data for Nifty50"""
    return await service.get_current_market_data()


@router.get("/options_chain", response_model=List[OptionsChainItem])
async def get_options_chain(service: MarketService = Depends(get_market_service)):
    """Get options chain with Greeks"""
    return await service.get_options_chain()


@router.get("/regime", response_model=MarketRegimeResponse)
async def get_market_regime(service: MarketService = Depends(get_market_service)):
    """Get current market regime classification"""
    return await service.get_market_regime()


@router.get("/predictions", response_model=PredictionResponse)
async def get_predictions(service: MarketService = Depends(get_market_service)):
    """Get ML model predictions"""
    return await service.get_predictions()
