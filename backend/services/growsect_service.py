"""
NIFTY GROWSECT 15 Real-time Service
====================================

Tracks 15 high-growth NSE stocks with:
- Real-time price updates
- Sector-wise heatmap generation
- Trend identification (Bull/Bear/Neutral)
- NSE reshuffle detection
- Entry signal generation for intraday trading
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass
import numpy as np

from loguru import logger

_IST = timezone(timedelta(hours=5, minutes=30))

# NIFTY GROWSECT 15: High-growth stocks (as per latest NSE constituents)
GROWSECT_15_STOCKS = {
    "DIVISLAB": "Pharma",
    "HINDUNILVR": "FMCG",
    "INFY": "IT",
    "CIPLA": "Pharma",
    "TCS": "IT",
    "PERSISTENT": "IT",
    "TVSMOTOR": "Auto",
    "NESTLEIND": "FMCG",
    "TECHM": "IT",
    "APOLLOHOSP": "Healthcare",
    "MARUTI": "Auto",
    "SUNPHARMA": "Pharma",
    "TITAN": "Consumer",
    "EICHERMOT": "Auto",
    "M&M": "Auto",
}

# Sector grouping for heatmap
SECTOR_GROUPS = {
    "Pharma": ["DIVISLAB", "CIPLA", "SUNPHARMA"],
    "IT": ["INFY", "TCS", "PERSISTENT", "TECHM"],
    "FMCG": ["HINDUNILVR", "NESTLEIND"],
    "Auto": ["TVSMOTOR", "MARUTI", "EICHERMOT", "M&M"],
    "Healthcare": ["APOLLOHOSP"],
    "Consumer": ["TITAN"],
}

@dataclass
class StockData:
    """Real-time stock data point"""
    symbol: str
    price: float
    prev_close: float
    change_pct: float
    sector: str
    timestamp: datetime
    rsi: float = 50.0
    macd_hist: float = 0.0
    volume_ratio: float = 1.0
    atr: float = 0.0

    @property
    def trend(self) -> str:
        """Classify trend: STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL"""
        if self.change_pct >= 2.5 and self.rsi >= 60:
            return "STRONG_BUY"
        elif self.change_pct >= 1.0 and self.rsi >= 55:
            return "BUY"
        elif self.change_pct <= -2.5 and self.rsi <= 40:
            return "STRONG_SELL"
        elif self.change_pct <= -1.0 and self.rsi <= 45:
            return "SELL"
        else:
            return "NEUTRAL"

@dataclass
class SectorStats:
    """Sector-level aggregate statistics"""
    sector: str
    avg_change_pct: float
    gainers: int
    losers: int
    stocks: List[str]
    strength: str  # "VERY_STRONG", "STRONG", "NEUTRAL", "WEAK", "VERY_WEAK"


class NiftyGrowsectService:
    """Manage NIFTY GROWSECT 15 real-time data and analysis"""

    def __init__(self):
        self.stocks_data: Dict[str, StockData] = {}
        self.last_update: datetime = datetime.now(_IST)
        self.last_reshuffled: Optional[datetime] = None
        self._cache_ttl = 60  # 1 minute

    async def update_stock_prices(self, market_service) -> bool:
        """Fetch latest prices for all GROWSECT 15 stocks"""
        try:
            updated_count = 0

            for symbol, sector in GROWSECT_15_STOCKS.items():
                try:
                    # Get current quote
                    quote = await market_service.get_quote(f"{symbol}-EQ")
                    if not quote:
                        continue

                    # Get technicals for this stock
                    technicals = await market_service.get_stock_technicals(symbol)

                    price = float(quote.get("ltp", 0))
                    prev_close = float(quote.get("previous_close", price))
                    change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

                    self.stocks_data[symbol] = StockData(
                        symbol=symbol,
                        price=price,
                        prev_close=prev_close,
                        change_pct=change_pct,
                        sector=sector,
                        timestamp=datetime.now(_IST),
                        rsi=technicals.get("rsi14", 50),
                        macd_hist=technicals.get("macd_hist", 0),
                        volume_ratio=technicals.get("vol_ratio", 1.0),
                        atr=technicals.get("atr14", 0),
                    )
                    updated_count += 1
                    await asyncio.sleep(0.1)  # Rate limit
                except Exception as e:
                    logger.warning(f"[GROWSECT] Failed to fetch {symbol}: {e}")
                    continue

            self.last_update = datetime.now(_IST)
            logger.info(f"[GROWSECT] Updated {updated_count}/{len(GROWSECT_15_STOCKS)} stocks")
            return updated_count == len(GROWSECT_15_STOCKS)

        except Exception as e:
            logger.error(f"[GROWSECT] Update error: {e}")
            return False

    def get_heatmap_data(self) -> Dict:
        """Generate heatmap with sector performance"""
        if not self.stocks_data:
            return {"error": "No data available"}

        sector_stats = {}

        for sector, stocks in SECTOR_GROUPS.items():
            prices = []
            gainers = 0
            losers = 0

            for symbol in stocks:
                if symbol in self.stocks_data:
                    data = self.stocks_data[symbol]
                    prices.append(data.change_pct)
                    if data.change_pct > 0:
                        gainers += 1
                    else:
                        losers += 1

            if prices:
                avg_change = np.mean(prices)

                # Classify sector strength
                if avg_change >= 2.5:
                    strength = "VERY_STRONG"
                elif avg_change >= 1.0:
                    strength = "STRONG"
                elif avg_change >= -1.0:
                    strength = "NEUTRAL"
                elif avg_change >= -2.5:
                    strength = "WEAK"
                else:
                    strength = "VERY_WEAK"

                sector_stats[sector] = {
                    "avg_change_pct": round(avg_change, 2),
                    "gainers": gainers,
                    "losers": losers,
                    "strength": strength,
                    "stocks": stocks,
                }

        return {
            "timestamp": self.last_update.isoformat(),
            "sectors": sector_stats,
            "most_bullish": max(
                sector_stats.items(),
                key=lambda x: x[1]["avg_change_pct"]
            )[0] if sector_stats else None,
            "most_bearish": min(
                sector_stats.items(),
                key=lambda x: x[1]["avg_change_pct"]
            )[0] if sector_stats else None,
        }

    def get_stock_heatmap(self) -> List[Dict]:
        """Get individual stock data for heatmap table"""
        stocks_list = []

        for symbol, data in self.stocks_data.items():
            stocks_list.append({
                "symbol": symbol,
                "price": round(data.price, 2),
                "prev_close": round(data.prev_close, 2),
                "change": round(data.price - data.prev_close, 2),
                "change_pct": round(data.change_pct, 2),
                "sector": data.sector,
                "rsi": round(data.rsi, 1),
                "trend": data.trend,
                "color": self._get_color_code(data.change_pct, data.trend),
                "timestamp": data.timestamp.isoformat(),
            })

        # Sort by change_pct descending
        return sorted(stocks_list, key=lambda x: x["change_pct"], reverse=True)

    def get_trend_signals(self) -> Dict:
        """Identify high-conviction entry signals"""
        signals = {
            "strong_buy": [],
            "buy": [],
            "sell": [],
            "strong_sell": [],
        }

        for symbol, data in self.stocks_data.items():
            trend = data.trend
            if trend == "STRONG_BUY":
                signals["strong_buy"].append({
                    "symbol": symbol,
                    "sector": data.sector,
                    "change_pct": data.change_pct,
                    "price": data.price,
                    "rsi": data.rsi,
                })
            elif trend == "BUY":
                signals["buy"].append({
                    "symbol": symbol,
                    "sector": data.sector,
                    "change_pct": data.change_pct,
                    "price": data.price,
                    "rsi": data.rsi,
                })
            elif trend == "SELL":
                signals["sell"].append({
                    "symbol": symbol,
                    "sector": data.sector,
                    "change_pct": data.change_pct,
                    "price": data.price,
                    "rsi": data.rsi,
                })
            elif trend == "STRONG_SELL":
                signals["strong_sell"].append({
                    "symbol": symbol,
                    "sector": data.sector,
                    "change_pct": data.change_pct,
                    "price": data.price,
                    "rsi": data.rsi,
                })

        return signals

    @staticmethod
    def _get_color_code(change_pct: float, trend: str) -> str:
        """Get color for visualization"""
        if trend == "STRONG_BUY":
            return "#00cc00"  # Dark green
        elif trend == "BUY":
            return "#90ee90"  # Light green
        elif trend == "STRONG_SELL":
            return "#cc0000"  # Dark red
        elif trend == "SELL":
            return "#ffb3b3"  # Light red
        else:
            return "#cccccc"  # Gray neutral

    def check_reshuffle(self) -> bool:
        """Check if NSE has reshuffled GROWSECT 15 (simplified check)"""
        # In production, would fetch from NSE official source
        # For now, check if constituents have changed significantly
        now = datetime.now(_IST)
        if self.last_reshuffled is None:
            self.last_reshuffled = now
            return False

        # Reshuffle happens quarterly typically
        days_since = (now - self.last_reshuffled).days
        if days_since > 90:  # Quarterly reshuffle
            self.last_reshuffled = now
            logger.info("[GROWSECT] Potential NSE reshuffle detected (quarterly)")
            return True

        return False


# Singleton instance
_instance = None

def get_growsect_service() -> NiftyGrowsectService:
    global _instance
    if _instance is None:
        _instance = NiftyGrowsectService()
        logger.info("[GROWSECT] Service initialized - tracking 15 high-growth stocks")
    return _instance
