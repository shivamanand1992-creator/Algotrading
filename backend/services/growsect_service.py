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
    """Real-time stock data point with comprehensive technical analysis"""
    symbol: str
    price: float
    prev_close: float
    change_pct: float
    sector: str
    timestamp: datetime
    # Technical indicators
    rsi: float = 50.0
    macd_hist: float = 0.0
    volume_ratio: float = 1.0
    atr: float = 0.0
    # Support/Resistance
    support: float = 0.0
    resistance: float = 0.0
    # Bollinger Bands
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    bb_pct: float = 50.0  # % B: position between bands (0-100)
    # MACD components
    macd_line: float = 0.0
    macd_signal: float = 0.0
    # Trend strength
    adx: float = 20.0
    # EMA alignment
    ema50: float = 0.0
    ema100: float = 0.0
    ema200: float = 0.0

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

    @property
    def technical_summary(self) -> Dict:
        """Get comprehensive technical analysis summary"""
        return {
            "support_resistance": {
                "support": round(self.support, 2),
                "resistance": round(self.resistance, 2),
                "distance_to_support_pct": round(((self.price - self.support) / self.price * 100), 2) if self.price > 0 else 0,
                "distance_to_resistance_pct": round(((self.resistance - self.price) / self.price * 100), 2) if self.price > 0 else 0,
            },
            "bollinger_bands": {
                "upper": round(self.bb_upper, 2),
                "middle": round(self.bb_middle, 2),
                "lower": round(self.bb_lower, 2),
                "pct_b": round(self.bb_pct, 1),  # 0 = at lower band, 100 = at upper band, 50 = at middle
                "status": "Overbought" if self.bb_pct > 80 else "Oversold" if self.bb_pct < 20 else "Neutral",
            },
            "momentum": {
                "macd_line": round(self.macd_line, 4),
                "macd_signal": round(self.macd_signal, 4),
                "macd_histogram": round(self.macd_hist, 4),
                "direction": "Bullish" if self.macd_hist > 0 else "Bearish",
            },
            "trend_strength": {
                "adx": round(self.adx, 1),
                "strength": "Very Strong" if self.adx > 40 else "Strong" if self.adx > 25 else "Weak",
            },
            "ema_alignment": {
                "ema50": round(self.ema50, 2),
                "ema100": round(self.ema100, 2),
                "ema200": round(self.ema200, 2),
                "bullish": (self.price > self.ema50 > self.ema100 > self.ema200),
                "status": "All EMAs aligned (Bullish)" if (self.price > self.ema50 > self.ema100 > self.ema200) else "Mixed signals",
            },
            "volume": {
                "ratio": round(self.volume_ratio, 2),
                "strength": "Strong" if self.volume_ratio > 1.3 else "Normal" if self.volume_ratio > 0.8 else "Weak",
            },
            "rsi": {
                "value": round(self.rsi, 1),
                "zone": "Overbought" if self.rsi > 70 else "Oversold" if self.rsi < 30 else "Neutral",
            },
        }

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

    async def update_stock_prices(self, market_service=None) -> bool:
        """Fetch latest prices for all GROWSECT 15 stocks using yfinance"""
        try:
            import yfinance as yf
            updated_count = 0

            # Fetch all 15 stocks at once
            symbols_list = list(GROWSECT_15_STOCKS.keys())
            tickers_str = " ".join([f"{s}.NS" for s in symbols_list])  # NSE format

            data = yf.download(tickers_str, period="5d", interval="1d", progress=False)

            if data.empty:
                logger.warning("[GROWSECT] No data returned from yfinance")
                return False

            # Extract close and other info
            for symbol in symbols_list:
                try:
                    # Get the latest data for this symbol
                    ticker = yf.Ticker(f"{symbol}.NS")
                    hist = ticker.history(period="5d")
                    info = ticker.info if hasattr(ticker, 'info') else {}

                    if hist.empty:
                        continue

                    # Get latest price (last row)
                    latest = hist.iloc[-1]
                    prev = hist.iloc[-2] if len(hist) > 1 else latest

                    price = float(latest['Close'])
                    prev_close = float(prev['Close']) if len(hist) > 1 else float(latest['Open'])
                    change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

                    # Estimate RSI from available data (simplified calculation)
                    rsi = self._calculate_simple_rsi(hist, symbol)

                    self.stocks_data[symbol] = StockData(
                        symbol=symbol,
                        price=price,
                        prev_close=prev_close,
                        change_pct=change_pct,
                        sector=GROWSECT_15_STOCKS[symbol],
                        timestamp=datetime.now(_IST),
                        rsi=rsi,
                        macd_hist=0.0,  # Would need additional calculation
                        volume_ratio=float(latest.get('Volume', 1000000)) / 1000000,
                        atr=0.0,  # Would need additional calculation
                    )
                    updated_count += 1
                    await asyncio.sleep(0.05)  # Rate limit
                except Exception as e:
                    logger.warning(f"[GROWSECT] Failed to fetch {symbol}: {e}")
                    continue

            self.last_update = datetime.now(_IST)
            logger.info(f"[GROWSECT] Updated {updated_count}/{len(GROWSECT_15_STOCKS)} stocks")
            return updated_count > 0

        except Exception as e:
            logger.error(f"[GROWSECT] Update error: {e}")
            return False

    @staticmethod
    def _calculate_simple_rsi(hist, symbol: str, period: int = 14) -> float:
        """Calculate simplified RSI from price history"""
        try:
            if len(hist) < period:
                return 50.0

            closes = hist['Close'].values
            deltas = np.diff(closes)

            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)

            avg_gain = np.mean(gains[-period:])
            avg_loss = np.mean(losses[-period:])

            if avg_loss == 0:
                return 100.0 if avg_gain > 0 else 50.0

            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return float(rsi)
        except Exception as e:
            logger.debug(f"[GROWSECT] RSI calc error for {symbol}: {e}")
            return 50.0

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
        """Get individual stock data for heatmap table with technical analysis"""
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
                # Technical analysis (expandable)
                "technical": data.technical_summary,
                "atr": round(data.atr, 2),
                "volume_ratio": round(data.volume_ratio, 2),
            })

        # Sort by change_pct descending
        return sorted(stocks_list, key=lambda x: x["change_pct"], reverse=True)

    def get_trend_signals(self) -> Dict:
        """Identify high-conviction entry signals with technical details"""
        signals = {
            "strong_buy": [],
            "buy": [],
            "sell": [],
            "strong_sell": [],
        }

        for symbol, data in self.stocks_data.items():
            trend = data.trend
            signal_data = {
                "symbol": symbol,
                "sector": data.sector,
                "change_pct": round(data.change_pct, 2),
                "price": round(data.price, 2),
                "rsi": round(data.rsi, 1),
                # Technical analysis details (for expandable view)
                "technical": data.technical_summary,
                "confidence": self._calculate_confidence(data),
            }

            if trend == "STRONG_BUY":
                signals["strong_buy"].append(signal_data)
            elif trend == "BUY":
                signals["buy"].append(signal_data)
            elif trend == "SELL":
                signals["sell"].append(signal_data)
            elif trend == "STRONG_SELL":
                signals["strong_sell"].append(signal_data)

        return signals

    def _calculate_confidence(self, data: StockData) -> Dict:
        """Calculate confidence score based on multiple technical factors"""
        score = 50.0

        # RSI contribution (±15)
        if 50 <= data.rsi <= 65:
            score += 15
        elif data.rsi > 70 or data.rsi < 40:
            score -= 5

        # MACD contribution (±10)
        if data.macd_hist > 0:
            score += 10

        # Volume contribution (±8)
        if data.volume_ratio > 1.3:
            score += 8
        elif data.volume_ratio < 0.8:
            score -= 5

        # Trend strength (ADX) (±10)
        if data.adx > 25:
            score += 10
        elif data.adx < 15:
            score -= 5

        # EMA alignment (±12)
        if data.price > data.ema50 > data.ema100 > data.ema200:
            score += 12

        # Bollinger Bands (±8)
        if data.bb_pct < 20:
            score += 8  # Oversold, potential bounce
        elif data.bb_pct > 80:
            score -= 3  # Overbought, caution

        return {
            "score": min(100, max(0, score)),
            "factors": {
                "rsi": "Bullish" if 50 <= data.rsi <= 70 else "Bearish" if data.rsi < 40 else "Neutral",
                "macd": "Bullish" if data.macd_hist > 0 else "Bearish",
                "volume": "Strong" if data.volume_ratio > 1.3 else "Weak" if data.volume_ratio < 0.8 else "Normal",
                "trend_strength": "Strong" if data.adx > 25 else "Weak",
                "ema_alignment": "Perfect" if data.price > data.ema50 > data.ema100 > data.ema200 else "Mixed",
            }
        }

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
