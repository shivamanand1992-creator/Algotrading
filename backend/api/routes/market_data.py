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


@router.get("/vix")
async def get_vix(
    interval: str = "FIFTEEN_MINUTE",
    days: int = 5,
    service: MarketService = Depends(get_market_service),
):
    """Get India VIX historical data for charting alongside Nifty."""
    if DEMO_MODE:
        return _demo_vix()
    return await service.get_vix_data(interval=interval, days=days)


@router.get("/global-cues")
async def get_global_cues(service: MarketService = Depends(get_market_service)):
    """Global market cues: S&P 500, NASDAQ, Nikkei, Hang Seng, Crude, Gold, USD/INR."""
    if DEMO_MODE:
        return _demo_global_cues()
    return await service.get_global_cues()


@router.get("/news")
async def get_news(service: MarketService = Depends(get_market_service)):
    """Latest Indian/global market news from multiple RSS feeds."""
    if DEMO_MODE:
        return _demo_news()
    # Return cached news; always try to fetch if cache is empty
    if not _cached_news:
        items = await service.get_news_summary()
        if items:
            set_cached_news(items)
    return _cached_news


@router.get("/technicals")
async def get_technicals(service: MarketService = Depends(get_market_service)):
    """Nifty 50 daily technical indicators: EMA9/21, SMA50, RSI14, MACD, Bollinger, ATR."""
    if DEMO_MODE:
        return _demo_technicals()
    return await service.get_nifty_technicals()


# Module-level news cache (populated by background loop at 09:00 IST)
_cached_news: list = []


def set_cached_news(items: list) -> None:
    """Called from background loop in main.py to refresh the news cache."""
    global _cached_news
    _cached_news = items


def _demo_global_cues():
    return [
        {"symbol": "^GSPC",    "name": "S&P 500",    "type": "index",     "ltp": 5287.76, "change": 23.45,  "change_pct": 0.45},
        {"symbol": "^IXIC",    "name": "NASDAQ",     "type": "index",     "ltp": 18407.0, "change": -45.20, "change_pct": -0.25},
        {"symbol": "^DJI",     "name": "Dow Jones",  "type": "index",     "ltp": 38721.0, "change": 112.0,  "change_pct": 0.29},
        {"symbol": "^N225",    "name": "Nikkei 225", "type": "index",     "ltp": 38710.0, "change": -80.0,  "change_pct": -0.21},
        {"symbol": "^HSI",     "name": "Hang Seng",  "type": "index",     "ltp": 18500.0, "change": 155.0,  "change_pct": 0.84},
        {"symbol": "CL=F",     "name": "Crude Oil",  "type": "commodity", "ltp": 78.45,   "change": -0.35,  "change_pct": -0.44},
        {"symbol": "GC=F",     "name": "Gold",       "type": "commodity", "ltp": 2320.0,  "change": 8.50,   "change_pct": 0.37},
        {"symbol": "USDINR=X", "name": "USD/INR",    "type": "forex",     "ltp": 83.47,   "change": 0.05,   "change_pct": 0.06},
    ]


def _demo_news():
    return [
        {"title": "Sensex rises 300 pts; Nifty tests 24,700 as IT stocks rally", "link": "#", "published": "Today, 9:10 AM"},
        {"title": "FII outflows moderate; DII support cushions market decline", "link": "#", "published": "Today, 8:45 AM"},
        {"title": "RBI holds rates steady; inflation within target band", "link": "#", "published": "Today, 8:30 AM"},
        {"title": "HDFC Bank Q4 results beat estimates; NIM expands", "link": "#", "published": "Yesterday"},
        {"title": "Crude oil steady near $78; no major supply disruptions", "link": "#", "published": "Yesterday"},
    ]


def _demo_technicals():
    import random, math
    base = 24500.0
    candles = []
    c = base - 600
    for i in range(45):
        c = round(c + random.uniform(-120, 150), 2)
        candles.append({
            "date":  f"2026-04-{(i % 30) + 1:02d}",
            "close": c,
            "ema9":  round(c - random.uniform(-30, 50), 2),
            "ema21": round(c - random.uniform(30, 120), 2),
            "bb_up": round(c + 180, 2),
            "bb_lo": round(c - 180, 2),
        })
    return {
        "last_close": base, "ema9": base - 45, "ema21": base - 210,
        "sma50": base - 380, "rsi14": 58.4, "macd_hist": 42.1,
        "atr14": 165.0, "bb_upper": base + 220, "bb_lower": base - 220,
        "bb_position": 62.0, "vol_ratio": 1.15,
        "momentum_5d": 1.2, "momentum_10d": 2.8, "momentum_20d": 4.1,
        "trend": "UPTREND", "signal": "BUY", "score": 4,
        "nb_action": "ACCUMULATE",
        "nb_reason": "Trend + momentum aligned. Good DCA window.",
        "candles": candles,
    }


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


def _demo_vix():
    """Generate ~50 synthetic VIX data points for demo mode."""
    import random
    from datetime import datetime, timedelta
    points = []
    vix = 14.5
    t = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0) - timedelta(days=1)
    for _ in range(50):
        vix += random.uniform(-0.4, 0.4)
        vix = max(10.0, min(28.0, vix))
        points.append({
            "timestamp": t.isoformat(),
            "open": round(vix, 2),
            "high": round(vix + random.uniform(0, 0.3), 2),
            "low":  round(vix - random.uniform(0, 0.3), 2),
            "close": round(vix, 2),
        })
        t += timedelta(minutes=15)
    return points
