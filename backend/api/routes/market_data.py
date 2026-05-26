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
from backend.config import config, DEMO_MODE

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
    if DEMO_MODE:
        return MarketDataResponse(
            symbol="NIFTY", ltp=24567.85, change=123.45, change_percentage=0.51,
            open=24444.40, high=24610.20, low=24398.75, volume=1250000,
            iv_percentile=42.5, pcr=0.87, timestamp="2024-05-25T10:30:00"
        )
    return await service.get_current_market_data()


@router.get("/options_chain", response_model=List[OptionsChainItem])
async def get_options_chain(service: MarketService = Depends(get_market_service)):
    """Get options chain with Greeks"""
    if DEMO_MODE:
        return []
    return await service.get_options_chain()


@router.get("/regime", response_model=MarketRegimeResponse)
async def get_market_regime(service: MarketService = Depends(get_market_service)):
    """Get current market regime classification"""
    if DEMO_MODE:
        return MarketRegimeResponse(
            regime="trending_up", confidence=0.78,
            regime_probabilities={"trending_up": 0.78, "ranging": 0.15, "volatile": 0.07},
            recommended_strategies=["trend", "scalping"]
        )
    return await service.get_market_regime()


@router.get("/predictions", response_model=PredictionResponse)
async def get_predictions(service: MarketService = Depends(get_market_service)):
    """Get ML model predictions"""
    if DEMO_MODE:
        return PredictionResponse(
            direction=1, direction_label="UP", confidence=0.72,
            direction_probabilities={"UP": 0.72, "FLAT": 0.18, "DOWN": 0.10},
            timestamp="2024-05-25T10:30:00"
        )
    return await service.get_predictions()


@router.get("/ohlcv")
async def get_ohlcv(
    interval: str = "FIFTEEN_MINUTE",
    days: int = 5,
    service: MarketService = Depends(get_market_service),
):
    """Get historical OHLCV candles for Nifty50 (used for line charts)."""
    if DEMO_MODE:
        return _demo_ohlcv()
    return await service.get_ohlcv_data(interval=interval, days=days)


def _demo_ohlcv():
    """Generate ~50 synthetic 15-min candles for demo mode."""
    import random
    from datetime import datetime, timedelta
    candles = []
    price = 24500.0
    t = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0) - timedelta(days=1)
    for _ in range(50):
        open_ = price
        change = random.uniform(-80, 80)
        close = round(open_ + change, 2)
        high  = round(max(open_, close) + random.uniform(0, 40), 2)
        low   = round(min(open_, close) - random.uniform(0, 40), 2)
        candles.append({
            "timestamp": t.isoformat(),
            "open": open_, "high": high, "low": low, "close": close,
            "volume": random.randint(50000, 200000),
        })
        price = close
        t += timedelta(minutes=15)
    return candles
