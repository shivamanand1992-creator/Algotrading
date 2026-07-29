"""
NIFTY GROWSECT 15 Real-time Heatmap API
========================================

GET  /api/growsect/heatmap              — Sector performance heatmap
GET  /api/growsect/stocks               — Individual stock performance
GET  /api/growsect/signals              — Entry signal identification
GET  /api/growsect/strongest            — Hottest stock today
POST /api/growsect/update-prices        — Manual price update (admin only)
"""

from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone, timedelta

from backend.services.growsect_service import get_growsect_service
from backend.api.routes.market_data import get_market_service

router = APIRouter(prefix="/api/growsect", tags=["growsect-heatmap"])

_IST = timezone(timedelta(hours=5, minutes=30))

# Demo mode
_DEMO_MODE = True


@router.get("/heatmap")
async def get_heatmap():
    """Get sector-wise heatmap (which sectors trending, which dipping)"""
    try:
        if _DEMO_MODE:
            return {
                "timestamp": datetime.now(_IST).isoformat(),
                "sectors": {
                    "IT": {
                        "avg_change_pct": 2.37,
                        "gainers": 4,
                        "losers": 0,
                        "strength": "VERY_STRONG",
                        "stocks": ["INFY", "TCS", "PERSISTENT", "TECHM"]
                    },
                    "Pharma": {
                        "avg_change_pct": 2.06,
                        "gainers": 3,
                        "losers": 0,
                        "strength": "STRONG",
                        "stocks": ["DIVISLAB", "CIPLA", "SUNPHARMA"]
                    },
                    "FMCG": {
                        "avg_change_pct": 1.01,
                        "gainers": 2,
                        "losers": 0,
                        "strength": "NEUTRAL",
                        "stocks": ["HINDUNILVR", "NESTLEIND"]
                    },
                    "Auto": {
                        "avg_change_pct": 0.48,
                        "gainers": 2,
                        "losers": 2,
                        "strength": "NEUTRAL",
                        "stocks": ["TVSMOTOR", "MARUTI", "EICHERMOT", "M&M"]
                    },
                    "Healthcare": {
                        "avg_change_pct": 0.52,
                        "gainers": 1,
                        "losers": 0,
                        "strength": "NEUTRAL",
                        "stocks": ["APOLLOHOSP"]
                    },
                    "Consumer": {
                        "avg_change_pct": -0.30,
                        "gainers": 0,
                        "losers": 1,
                        "strength": "WEAK",
                        "stocks": ["TITAN"]
                    },
                },
                "most_bullish": "IT",
                "most_bearish": "Consumer",
                "message": "📊 IT & Pharma leading today. Consumer weak. Avoid shorting Tech/Pharma."
            }

        service = get_growsect_service()
        return service.get_heatmap_data()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stocks")
async def get_stocks():
    """Get individual stock performance for all GROWSECT 15"""
    try:
        if _DEMO_MODE:
            return {
                "timestamp": datetime.now(_IST).isoformat(),
                "stocks": [
                    {"symbol": "DIVISLAB", "price": 7760.00, "prev_close": 7736.05, "change": 23.95, "change_pct": 4.51, "sector": "Pharma", "rsi": 68.2, "trend": "STRONG_BUY", "color": "#00cc00"},
                    {"symbol": "HINDUNILVR", "price": 2112.10, "prev_close": 2023.40, "change": 88.70, "change_pct": 4.42, "sector": "FMCG", "rsi": 65.5, "trend": "STRONG_BUY", "color": "#00cc00"},
                    {"symbol": "INFY", "price": 1152.80, "prev_close": 1107.25, "change": 45.55, "change_pct": 4.26, "sector": "IT", "rsi": 70.1, "trend": "STRONG_BUY", "color": "#00cc00"},
                    {"symbol": "CIPLA", "price": 1484.30, "prev_close": 1444.55, "change": 39.75, "change_pct": 2.75, "sector": "Pharma", "rsi": 62.3, "trend": "BUY", "color": "#90ee90"},
                    {"symbol": "TCS", "price": 2444.00, "prev_close": 2397.50, "change": 46.50, "change_pct": 1.92, "sector": "IT", "rsi": 58.9, "trend": "BUY", "color": "#90ee90"},
                    {"symbol": "PERSISTENT", "price": 5519.20, "prev_close": 5445.10, "change": 74.10, "change_pct": 1.67, "sector": "IT", "rsi": 56.4, "trend": "BUY", "color": "#90ee90"},
                    {"symbol": "TVSMOTOR", "price": 4057.00, "prev_close": 3991.25, "change": 65.75, "change_pct": 1.59, "sector": "Auto", "rsi": 54.2, "trend": "NEUTRAL", "color": "#cccccc"},
                    {"symbol": "NESTLEIND", "price": 1509.50, "prev_close": 1491.15, "change": 18.35, "change_pct": 1.19, "sector": "FMCG", "rsi": 51.8, "trend": "NEUTRAL", "color": "#cccccc"},
                    {"symbol": "TECHM", "price": 1648.60, "prev_close": 1624.85, "change": 23.75, "change_pct": 0.82, "sector": "IT", "rsi": 49.5, "trend": "NEUTRAL", "color": "#cccccc"},
                    {"symbol": "APOLLOHOSP", "price": 8949.50, "prev_close": 8894.50, "change": 55.00, "change_pct": 0.52, "sector": "Healthcare", "rsi": 48.1, "trend": "NEUTRAL", "color": "#cccccc"},
                    {"symbol": "MARUTI", "price": 13863.00, "prev_close": 13804.50, "change": 58.50, "change_pct": 0.44, "sector": "Auto", "rsi": 47.3, "trend": "NEUTRAL", "color": "#cccccc"},
                    {"symbol": "SUNPHARMA", "price": 1975.70, "prev_close": 1954.50, "change": 21.20, "change_pct": -0.05, "sector": "Pharma", "rsi": 45.2, "trend": "NEUTRAL", "color": "#cccccc"},
                    {"symbol": "TITAN", "price": 4835.00, "prev_close": 4850.55, "change": -15.55, "change_pct": -0.30, "sector": "Consumer", "rsi": 42.5, "trend": "SELL", "color": "#ffb3b3"},
                    {"symbol": "EICHERMOT", "price": 7781.50, "prev_close": 7835.25, "change": -53.75, "change_pct": -0.70, "sector": "Auto", "rsi": 38.9, "trend": "SELL", "color": "#ffb3b3"},
                    {"symbol": "M&M", "price": 3223.50, "prev_close": 3268.35, "change": -44.85, "change_pct": -1.46, "sector": "Auto", "rsi": 35.2, "trend": "STRONG_SELL", "color": "#cc0000"},
                ],
                "message": "🟢 13 gainers, 2 losers. IT & Pharma strongest. Auto mixed. M&M weakest."
            }

        service = get_growsect_service()
        return {"timestamp": datetime.now(_IST).isoformat(), "stocks": service.get_stock_heatmap()}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals")
async def get_signals():
    """Get entry signals: which stocks to trade today (intraday)"""
    try:
        if _DEMO_MODE:
            return {
                "timestamp": datetime.now(_IST).isoformat(),
                "strong_buy": [
                    {"symbol": "DIVISLAB", "sector": "Pharma", "change_pct": 4.51, "price": 7760.00, "rsi": 68.2},
                    {"symbol": "HINDUNILVR", "sector": "FMCG", "change_pct": 4.42, "price": 2112.10, "rsi": 65.5},
                    {"symbol": "INFY", "sector": "IT", "change_pct": 4.26, "price": 1152.80, "rsi": 70.1},
                ],
                "buy": [
                    {"symbol": "CIPLA", "sector": "Pharma", "change_pct": 2.75, "price": 1484.30, "rsi": 62.3},
                    {"symbol": "TCS", "sector": "IT", "change_pct": 1.92, "price": 2444.00, "rsi": 58.9},
                ],
                "sell": [
                    {"symbol": "TITAN", "sector": "Consumer", "change_pct": -0.30, "price": 4835.00, "rsi": 42.5},
                    {"symbol": "EICHERMOT", "sector": "Auto", "change_pct": -0.70, "price": 7781.50, "rsi": 38.9},
                ],
                "strong_sell": [
                    {"symbol": "M&M", "sector": "Auto", "change_pct": -1.46, "price": 3223.50, "rsi": 35.2},
                ],
                "recommendation": "🟢 STRONG_BUY 3 stocks (DIVISLAB, HINDUNILVR, INFY). BUY 2 more (CIPLA, TCS). Avoid M&M & EICHERMOT."
            }

        service = get_growsect_service()
        return {"timestamp": datetime.now(_IST).isoformat(), "signals": service.get_trend_signals()}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strongest")
async def get_strongest():
    """Get the hottest stock today (for quick intraday trade)"""
    try:
        if _DEMO_MODE:
            return {
                "timestamp": datetime.now(_IST).isoformat(),
                "hottest_stock": {
                    "symbol": "DIVISLAB",
                    "sector": "Pharma",
                    "price": 7760.00,
                    "change_pct": 4.51,
                    "rsi": 68.2,
                    "trend": "STRONG_BUY",
                    "recommendation": "✅ Premium entry signal: 4.51% up, RSI 68.2 (overbought but momentum strong)",
                    "entry_target": 7760.00,
                    "stop_loss": 7650.00,
                    "profit_target": 7900.00,
                    "risk_reward": 1.96
                }
            }

        service = get_growsect_service()
        stocks = service.get_stock_heatmap()
        if stocks:
            hottest = stocks[0]  # First is highest gainer
            return {
                "timestamp": datetime.now(_IST).isoformat(),
                "hottest_stock": hottest
            }
        return {"error": "No stock data available"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-prices")
async def update_prices():
    """Manually trigger price update (admin only)"""
    try:
        service = get_growsect_service()
        market_svc = get_market_service()

        success = await service.update_stock_prices(market_svc)

        if success:
            return {"status": "success", "message": "Prices updated for all GROWSECT 15 stocks"}
        else:
            return {"status": "partial", "message": "Some stocks failed to update"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
