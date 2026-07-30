"""
NIFTY GROWSECT 15 Real-time Heatmap API
========================================

GET  /api/growsect/heatmap              — Sector performance heatmap
GET  /api/growsect/stocks               — Individual stock performance
GET  /api/growsect/signals              — Entry signal identification
GET  /api/growsect/strongest            — Hottest stock today
POST /api/growsect/update-prices        — Manual price update (admin only)

INTRADAY TRENDING ALERTS:
GET  /api/growsect/intraday-config      — Get watchlist & telegram users
POST /api/growsect/intraday-config/watchlist — Update stock watchlist
POST /api/growsect/intraday-config/telegram-users — Add telegram user
DELETE /api/growsect/intraday-config/telegram-users/{chat_id} — Remove user
GET  /api/growsect/intraday-alerts      — Get today's intraday movers (stock + sector trending)
"""

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from backend.services.growsect_service import get_growsect_service
from backend.services import growsect_intraday_alerts
from backend.api.routes.market_data import get_market_service

router = APIRouter(prefix="/api/growsect", tags=["growsect-heatmap"])

_IST = timezone(timedelta(hours=5, minutes=30))

# Demo mode
_DEMO_MODE = False


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

        # Fetch fresh data if stale (data older than 90 seconds)
        if not service.stocks_data or (datetime.now(_IST) - service.last_update).total_seconds() > 90:
            market_svc = get_market_service()
            await service.update_stock_prices(market_svc)

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

        # Fetch fresh data if stale (data older than 90 seconds)
        if not service.stocks_data or (datetime.now(_IST) - service.last_update).total_seconds() > 90:
            market_svc = get_market_service()
            await service.update_stock_prices(market_svc)

        return {"timestamp": datetime.now(_IST).isoformat(), "stocks": service.get_stock_heatmap()}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals")
async def get_signals():
    """Get entry signals with comprehensive technical analysis"""
    try:
        if _DEMO_MODE:
            return {
                "timestamp": datetime.now(_IST).isoformat(),
                "strong_buy": [
                    {
                        "symbol": "DIVISLAB",
                        "sector": "Pharma",
                        "change_pct": 4.51,
                        "price": 7760.00,
                        "rsi": 68.2,
                        "confidence": {"score": 82, "factors": {"rsi": "Bullish", "macd": "Bullish", "volume": "Strong", "trend_strength": "Strong", "ema_alignment": "Perfect"}},
                        "technical": {
                            "support_resistance": {"support": 7650.00, "resistance": 7900.00, "distance_to_support_pct": 1.43, "distance_to_resistance_pct": 1.81},
                            "bollinger_bands": {"upper": 7850.00, "middle": 7750.00, "lower": 7650.00, "pct_b": 65.0, "status": "Neutral"},
                            "momentum": {"macd_line": 0.45, "macd_signal": 0.35, "macd_histogram": 0.10, "direction": "Bullish"},
                            "trend_strength": {"adx": 28.5, "strength": "Strong"},
                            "ema_alignment": {"ema50": 7680.00, "ema100": 7600.00, "ema200": 7520.00, "bullish": True, "status": "All EMAs aligned (Bullish)"},
                            "volume": {"ratio": 1.45, "strength": "Strong"},
                            "rsi": {"value": 68.2, "zone": "Overbought"},
                        }
                    },
                    {
                        "symbol": "HINDUNILVR",
                        "sector": "FMCG",
                        "change_pct": 4.42,
                        "price": 2112.10,
                        "rsi": 65.5,
                        "confidence": {"score": 79, "factors": {"rsi": "Bullish", "macd": "Bullish", "volume": "Strong", "trend_strength": "Strong", "ema_alignment": "Perfect"}},
                        "technical": {
                            "support_resistance": {"support": 2050.00, "resistance": 2180.00, "distance_to_support_pct": 2.94, "distance_to_resistance_pct": 3.14},
                            "bollinger_bands": {"upper": 2150.00, "middle": 2080.00, "lower": 2010.00, "pct_b": 62.0, "status": "Neutral"},
                            "momentum": {"macd_line": 0.32, "macd_signal": 0.25, "macd_histogram": 0.07, "direction": "Bullish"},
                            "trend_strength": {"adx": 26.2, "strength": "Strong"},
                            "ema_alignment": {"ema50": 2050.00, "ema100": 1980.00, "ema200": 1920.00, "bullish": True, "status": "All EMAs aligned (Bullish)"},
                            "volume": {"ratio": 1.38, "strength": "Strong"},
                            "rsi": {"value": 65.5, "zone": "Neutral"},
                        }
                    },
                    {
                        "symbol": "INFY",
                        "sector": "IT",
                        "change_pct": 4.26,
                        "price": 1152.80,
                        "rsi": 70.1,
                        "confidence": {"score": 80, "factors": {"rsi": "Bullish", "macd": "Bullish", "volume": "Strong", "trend_strength": "Strong", "ema_alignment": "Perfect"}},
                        "technical": {
                            "support_resistance": {"support": 1120.00, "resistance": 1190.00, "distance_to_support_pct": 2.85, "distance_to_resistance_pct": 3.22},
                            "bollinger_bands": {"upper": 1180.00, "middle": 1140.00, "lower": 1100.00, "pct_b": 72.0, "status": "Neutral"},
                            "momentum": {"macd_line": 0.38, "macd_signal": 0.28, "macd_histogram": 0.10, "direction": "Bullish"},
                            "trend_strength": {"adx": 27.8, "strength": "Strong"},
                            "ema_alignment": {"ema50": 1130.00, "ema100": 1090.00, "ema200": 1050.00, "bullish": True, "status": "All EMAs aligned (Bullish)"},
                            "volume": {"ratio": 1.42, "strength": "Strong"},
                            "rsi": {"value": 70.1, "zone": "Overbought"},
                        }
                    },
                ],
                "buy": [
                    {
                        "symbol": "CIPLA",
                        "sector": "Pharma",
                        "change_pct": 2.75,
                        "price": 1484.30,
                        "rsi": 62.3,
                        "confidence": {"score": 71, "factors": {"rsi": "Bullish", "macd": "Bullish", "volume": "Normal", "trend_strength": "Strong", "ema_alignment": "Perfect"}},
                        "technical": {
                            "support_resistance": {"support": 1450.00, "resistance": 1520.00, "distance_to_support_pct": 2.36, "distance_to_resistance_pct": 2.41},
                            "bollinger_bands": {"upper": 1510.00, "middle": 1460.00, "lower": 1410.00, "pct_b": 58.0, "status": "Neutral"},
                            "momentum": {"macd_line": 0.25, "macd_signal": 0.18, "macd_histogram": 0.07, "direction": "Bullish"},
                            "trend_strength": {"adx": 23.5, "strength": "Weak"},
                            "ema_alignment": {"ema50": 1460.00, "ema100": 1430.00, "ema200": 1400.00, "bullish": True, "status": "All EMAs aligned (Bullish)"},
                            "volume": {"ratio": 1.15, "strength": "Normal"},
                            "rsi": {"value": 62.3, "zone": "Neutral"},
                        }
                    },
                    {
                        "symbol": "TCS",
                        "sector": "IT",
                        "change_pct": 1.92,
                        "price": 2444.00,
                        "rsi": 58.9,
                        "confidence": {"score": 68, "factors": {"rsi": "Bullish", "macd": "Bullish", "volume": "Normal", "trend_strength": "Weak", "ema_alignment": "Perfect"}},
                        "technical": {
                            "support_resistance": {"support": 2400.00, "resistance": 2500.00, "distance_to_support_pct": 1.82, "distance_to_resistance_pct": 2.29},
                            "bollinger_bands": {"upper": 2480.00, "middle": 2420.00, "lower": 2360.00, "pct_b": 52.0, "status": "Neutral"},
                            "momentum": {"macd_line": 0.18, "macd_signal": 0.12, "macd_histogram": 0.06, "direction": "Bullish"},
                            "trend_strength": {"adx": 21.2, "strength": "Weak"},
                            "ema_alignment": {"ema50": 2420.00, "ema100": 2390.00, "ema200": 2350.00, "bullish": True, "status": "All EMAs aligned (Bullish)"},
                            "volume": {"ratio": 0.95, "strength": "Normal"},
                            "rsi": {"value": 58.9, "zone": "Neutral"},
                        }
                    },
                ],
                "sell": [
                    {
                        "symbol": "TITAN",
                        "sector": "Consumer",
                        "change_pct": -0.30,
                        "price": 4835.00,
                        "rsi": 42.5,
                        "confidence": {"score": 35, "factors": {"rsi": "Neutral", "macd": "Bearish", "volume": "Weak", "trend_strength": "Weak", "ema_alignment": "Mixed"}},
                        "technical": {
                            "support_resistance": {"support": 4750.00, "resistance": 4900.00, "distance_to_support_pct": 1.79, "distance_to_resistance_pct": 1.34},
                            "bollinger_bands": {"upper": 4900.00, "middle": 4800.00, "lower": 4700.00, "pct_b": 45.0, "status": "Neutral"},
                            "momentum": {"macd_line": -0.05, "macd_signal": 0.02, "macd_histogram": -0.07, "direction": "Bearish"},
                            "trend_strength": {"adx": 18.5, "strength": "Weak"},
                            "ema_alignment": {"ema50": 4850.00, "ema100": 4880.00, "ema200": 4820.00, "bullish": False, "status": "Mixed"},
                            "volume": {"ratio": 0.75, "strength": "Weak"},
                            "rsi": {"value": 42.5, "zone": "Neutral"},
                        }
                    },
                ],
                "strong_sell": [
                    {
                        "symbol": "M&M",
                        "sector": "Auto",
                        "change_pct": -1.46,
                        "price": 3223.50,
                        "rsi": 35.2,
                        "confidence": {"score": 20, "factors": {"rsi": "Bearish", "macd": "Bearish", "volume": "Weak", "trend_strength": "Weak", "ema_alignment": "Bearish"}},
                        "technical": {
                            "support_resistance": {"support": 3100.00, "resistance": 3300.00, "distance_to_support_pct": 3.81, "distance_to_resistance_pct": 2.32},
                            "bollinger_bands": {"upper": 3310.00, "middle": 3220.00, "lower": 3130.00, "pct_b": 35.0, "status": "Oversold"},
                            "momentum": {"macd_line": -0.18, "macd_signal": -0.10, "macd_histogram": -0.08, "direction": "Bearish"},
                            "trend_strength": {"adx": 15.2, "strength": "Weak"},
                            "ema_alignment": {"ema50": 3280.00, "ema100": 3320.00, "ema200": 3350.00, "bullish": False, "status": "All EMAs pointing down (Bearish)"},
                            "volume": {"ratio": 0.65, "strength": "Weak"},
                            "rsi": {"value": 35.2, "zone": "Oversold"},
                        }
                    },
                ],
                "recommendation": "🟢 STRONG_BUY 3 stocks (DIVISLAB, HINDUNILVR, INFY). All have perfect EMA alignment & strong momentum. BUY 2 more (CIPLA, TCS) for secondary positions. AVOID M&M (bearish signals, oversold)."
            }

        service = get_growsect_service()

        # Fetch fresh data if stale (data older than 90 seconds)
        if not service.stocks_data or (datetime.now(_IST) - service.last_update).total_seconds() > 90:
            market_svc = get_market_service()
            await service.update_stock_prices(market_svc)

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

        # Fetch fresh data if stale (data older than 90 seconds)
        if not service.stocks_data or (datetime.now(_IST) - service.last_update).total_seconds() > 90:
            market_svc = get_market_service()
            await service.update_stock_prices(market_svc)

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


# ─── INTRADAY TRENDING ALERTS ────────────────────────────────────────────


@router.get("/intraday-config")
async def get_intraday_config():
    """Get current intraday alerts config (watchlist + telegram users)"""
    try:
        config = growsect_intraday_alerts.get_config()
        return {
            "watchlist": config.get("watchlist", {}),
            "watchlist_count": len(config.get("watchlist", {})),
            "telegram_ids": config.get("telegram_ids", []),
            "telegram_count": len(config.get("telegram_ids", [])),
            "created_at": config.get("created_at"),
            "watchlist_updated_at": config.get("watchlist_updated_at"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/intraday-config/watchlist")
async def update_intraday_watchlist(watchlist: Dict[str, str]):
    """
    Update the GROWSECT15 watchlist (for index reshuffles)

    Example:
    {
        "DIVISLAB": "Pharma",
        "INFY": "IT",
        ...
    }
    """
    try:
        if not watchlist:
            raise HTTPException(status_code=400, detail="Watchlist cannot be empty")

        success = growsect_intraday_alerts.update_watchlist(watchlist)

        if success:
            return {
                "status": "success",
                "message": f"Watchlist updated with {len(watchlist)} stocks",
                "watchlist": watchlist
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to save watchlist")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/intraday-config/telegram-users")
async def add_telegram_user(chat_id: int = Query(..., description="Telegram chat ID")):
    """Add a new Telegram user to receive intraday alerts"""
    try:
        if chat_id <= 0:
            raise HTTPException(status_code=400, detail="Invalid chat ID")

        success = growsect_intraday_alerts.add_telegram_user(chat_id)

        if success:
            users = growsect_intraday_alerts.get_telegram_users()
            return {
                "status": "success",
                "message": f"Added Telegram user {chat_id}",
                "chat_id": chat_id,
                "total_users": len(users),
                "all_users": users
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to add user")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/intraday-config/telegram-users/{chat_id}")
async def remove_telegram_user(chat_id: int):
    """Remove a Telegram user from intraday alerts"""
    try:
        success = growsect_intraday_alerts.remove_telegram_user(chat_id)

        if success:
            users = growsect_intraday_alerts.get_telegram_users()
            return {
                "status": "success",
                "message": f"Removed Telegram user {chat_id}",
                "total_users": len(users),
                "all_users": users
            }
        else:
            raise HTTPException(status_code=404, detail=f"Chat ID {chat_id} not found")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/intraday-alerts")
async def get_intraday_alerts():
    """
    Get today's GROWSECT15 stocks where BOTH stock and sector are trending (up)
    Ranked by % gain for intraday trading

    Returns stocks that have:
    - Stock % change > 0 (stock is up)
    - Sector % change > 0 (sector is also up)
    """
    try:
        service = get_growsect_service()

        # Fetch fresh data if stale (data older than 90 seconds)
        if not service.stocks_data or (datetime.now(_IST) - service.last_update).total_seconds() > 90:
            market_svc = get_market_service()
            await service.update_stock_prices(market_svc)

        # Get all stocks
        all_stocks = service.get_stock_heatmap()
        if not all_stocks:
            return {
                "timestamp": datetime.now(_IST).isoformat(),
                "intraday_movers": [],
                "message": "No stock data available"
            }

        # Get sector data
        heatmap = service.get_heatmap_data()
        sector_changes = {
            sector_name: data.get("avg_change_pct", 0)
            for sector_name, data in heatmap.get("sectors", {}).items()
        }

        # Filter: stock % > 0 AND sector % > 0, then rank by stock %
        intraday_movers = []
        for stock in all_stocks:
            stock_pct = stock.get("change_pct", 0)
            sector = stock.get("sector", "")
            sector_pct = sector_changes.get(sector, 0)

            if stock_pct > 0 and sector_pct > 0:
                intraday_movers.append({
                    "symbol": stock.get("symbol"),
                    "sector": sector,
                    "price": stock.get("price"),
                    "stock_change_pct": round(stock_pct, 2),
                    "sector_change_pct": round(sector_pct, 2),
                    "combined_momentum": round(stock_pct + sector_pct, 2),
                    "rsi": stock.get("rsi"),
                    "trend": stock.get("trend"),
                })

        # Sort by stock % gain descending
        intraday_movers.sort(key=lambda x: x["stock_change_pct"], reverse=True)

        return {
            "timestamp": datetime.now(_IST).isoformat(),
            "count": len(intraday_movers),
            "intraday_movers": intraday_movers,
            "message": f"📈 {len(intraday_movers)} stocks trending with sector support — ideal for intraday trading"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
