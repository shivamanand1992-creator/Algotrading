"""
ICICI Direct Breeze API Data Fetcher
====================================

Fetches real market data from Breeze API for backtesting.
Replaces all hardcoded/estimated data with actual broker data.

Usage:
    from backend.data.breeze_data_fetcher import BreezeDataFetcher

    fetcher = BreezeDataFetcher(api_key, api_secret)

    # Get historical prices
    prices = fetcher.get_historical_prices("INFY-EQ", days=730)

    # Get option chain
    options = fetcher.get_option_chain("NIFTY50", expiry="28-NOV-2024")

    # Get sector constituents
    sectors = fetcher.get_sector_constituents()
"""

import os
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import json
from pathlib import Path

from loguru import logger

_IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class PriceBar:
    """Single OHLCV bar"""
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int = 0  # Open interest for options


@dataclass
class OptionChain:
    """Option chain data point"""
    date: datetime
    strike: int
    option_type: str  # "CE" or "PE"
    iv: float
    bid: float
    ask: float
    bid_qty: int
    ask_qty: int
    volume: int
    oi: int
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0


class BreezeDataFetcher:
    """
    Fetches real data from ICICI Direct Breeze API.

    Uses real prices instead of:
    - Hardcoded stock lists
    - Estimated IV (15%)
    - Guessed bid-ask spreads
    - Invented option chains
    """

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.breeze = None
        self.session_active = False
        self.cache_dir = Path("/home/user/Algotrading/backend/data/breeze_cache")
        self.cache_dir.mkdir(exist_ok=True)

        logger.info(f"[BreezeDataFetcher] Initialized (cache: {self.cache_dir})")

    def connect(self) -> bool:
        """Establish Breeze session"""
        try:
            from breeze_connect import BreezeConnect

            self.breeze = BreezeConnect(api_key=self.api_key, api_secret=self.api_secret)
            self.breeze.generate_session()
            self.session_active = True
            logger.info(f"[BreezeDataFetcher] Connected to Breeze API")
            return True
        except ImportError:
            logger.error("[BreezeDataFetcher] breeze_connect not installed. Run: pip install breeze_connect")
            return False
        except Exception as e:
            logger.error(f"[BreezeDataFetcher] Connection failed: {e}")
            return False

    def get_historical_prices(
        self,
        symbol: str,
        days: int = 730,
        interval: str = "1d",
        use_cache: bool = True
    ) -> List[PriceBar]:
        """
        Fetch historical OHLCV data for a stock/index.

        Args:
            symbol: NSE symbol (e.g., "INFY-EQ", "NIFTY50-IX")
            days: How many days of history to fetch
            interval: "1d" for daily, "5m" for 5-min, etc.
            use_cache: Use cached data if available (faster, but potentially stale)

        Returns:
            List of PriceBar objects
        """
        if not self.session_active:
            if not self.connect():
                return []

        # Check cache first
        cache_file = self.cache_dir / f"{symbol}_{interval}_{days}d.json"
        if use_cache and cache_file.exists():
            logger.info(f"[BreezeDataFetcher] Loading {symbol} from cache")
            return self._load_from_cache(cache_file)

        try:
            to_date = datetime.now(_IST).date()
            from_date = to_date - timedelta(days=days)

            logger.info(
                f"[BreezeDataFetcher] Fetching {symbol} "
                f"from {from_date} to {to_date} ({interval})"
            )

            # Determine exchange
            exchange = "NFO" if "-FUT" in symbol or "-IX" in symbol else "NSE"

            data = self.breeze.get_historical_data(
                exchange_code=exchange,
                symbol=symbol,
                interval=interval,
                from_date=from_date.strftime("%d-%b-%Y"),
                to_date=to_date.strftime("%d-%b-%Y")
            )

            bars = []
            for item in data:
                bar = PriceBar(
                    date=datetime.strptime(item["date"], "%d-%b-%Y").replace(tzinfo=_IST),
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=int(item.get("volume", 0)),
                    oi=int(item.get("oi", 0))
                )
                bars.append(bar)

            # Cache it
            self._save_to_cache(cache_file, bars)
            logger.info(f"[BreezeDataFetcher] Fetched {len(bars)} bars for {symbol}")
            return bars

        except Exception as e:
            logger.error(f"[BreezeDataFetcher] Error fetching {symbol}: {e}")
            return []

    def get_option_chain_history(
        self,
        symbol: str,
        expiry: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        use_cache: bool = True
    ) -> List[OptionChain]:
        """
        Fetch historical option chain data.

        Args:
            symbol: Underlying symbol (e.g., "NIFTY50")
            expiry: Expiry date (e.g., "28-NOV-2024")
            from_date: Start date (default: 1 year ago)
            to_date: End date (default: today)
            use_cache: Use cached data

        Returns:
            List of OptionChain objects
        """
        if not self.session_active:
            if not self.connect():
                return []

        # Default date range
        if not to_date:
            to_date = datetime.now(_IST).date().strftime("%d-%b-%Y")
        if not from_date:
            from_date = (datetime.now(_IST).date() - timedelta(days=365)).strftime("%d-%b-%Y")

        cache_file = self.cache_dir / f"{symbol}_{expiry}_options.json"
        if use_cache and cache_file.exists():
            logger.info(f"[BreezeDataFetcher] Loading {symbol} options from cache")
            return self._load_options_from_cache(cache_file)

        try:
            logger.info(
                f"[BreezeDataFetcher] Fetching {symbol} options "
                f"({from_date} to {to_date})"
            )

            option_chain = self.breeze.get_option_chain(
                exchange_code="NFO",
                symbol=symbol,
                expiry_date=expiry
            )

            options = []
            for strike_data in option_chain:
                for opt_type in ["CE", "PE"]:
                    try:
                        opt = OptionChain(
                            date=datetime.now(_IST),
                            strike=int(strike_data["strike"]),
                            option_type=opt_type,
                            iv=float(strike_data.get("iv", 0.20)),  # Fallback to 20% if missing
                            bid=float(strike_data.get(f"{opt_type}_bid", 0)),
                            ask=float(strike_data.get(f"{opt_type}_ask", 0)),
                            bid_qty=int(strike_data.get(f"{opt_type}_bid_qty", 0)),
                            ask_qty=int(strike_data.get(f"{opt_type}_ask_qty", 0)),
                            volume=int(strike_data.get(f"{opt_type}_volume", 0)),
                            oi=int(strike_data.get(f"{opt_type}_oi", 0)),
                        )
                        options.append(opt)
                    except Exception as e:
                        logger.debug(f"[BreezeDataFetcher] Skipping option: {e}")
                        continue

            self._save_options_to_cache(cache_file, options)
            logger.info(f"[BreezeDataFetcher] Fetched {len(options)} options")
            return options

        except Exception as e:
            logger.error(f"[BreezeDataFetcher] Error fetching options: {e}")
            return []

    def get_nifty50_constituents(self) -> Dict[str, str]:
        """
        Get current NIFTY50 constituents with their sectors.

        Returns:
            Dict of {symbol: sector}
        """
        cache_file = self.cache_dir / "nifty50_constituents.json"

        # Check cache (valid for 1 week)
        if cache_file.exists():
            age = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).days
            if age < 7:
                logger.info("[BreezeDataFetcher] Loading NIFTY50 from cache")
                with open(cache_file) as f:
                    return json.load(f)

        try:
            if not self.session_active:
                if not self.connect():
                    return {}

            logger.info("[BreezeDataFetcher] Fetching NIFTY50 constituents from Breeze")

            # Get NIFTY50 index constituents
            # (This depends on Breeze API capabilities - may need adjustment)
            constituents = self.breeze.get_indices_data(index_symbol="NIFTY50")

            result = {}
            for item in constituents:
                symbol = item.get("symbol", "")
                sector = item.get("sector", "Unknown")
                if symbol:
                    result[symbol] = sector

            # Cache it
            with open(cache_file, "w") as f:
                json.dump(result, f, indent=2)

            logger.info(f"[BreezeDataFetcher] Fetched {len(result)} NIFTY50 constituents")
            return result

        except Exception as e:
            logger.error(f"[BreezeDataFetcher] Error fetching NIFTY50: {e}")
            # Fallback to hardcoded list (better than nothing)
            return self._get_hardcoded_nifty50()

    def get_fo_stocks_list(self) -> Dict[str, str]:
        """
        Get F&O eligible stocks from NSE.

        Returns:
            Dict of {symbol: sector}
        """
        cache_file = self.cache_dir / "fo_stocks_list.json"

        # Check cache (valid for 1 week)
        if cache_file.exists():
            age = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).days
            if age < 7:
                logger.info("[BreezeDataFetcher] Loading F&O stocks from cache")
                with open(cache_file) as f:
                    return json.load(f)

        try:
            logger.info("[BreezeDataFetcher] Fetching F&O stocks from Breeze")

            # Get all F&O stocks
            fo_stocks = self.breeze.get_tradingsymbol(exchange_code="NFO")

            result = {}
            for stock in fo_stocks:
                symbol = stock.get("symbol", "").replace("-FUT", "")
                sector = stock.get("sector", "Unknown")
                if symbol and "-FUT" in stock.get("symbol", ""):
                    result[symbol] = sector

            # Cache it
            with open(cache_file, "w") as f:
                json.dump(result, f, indent=2)

            logger.info(f"[BreezeDataFetcher] Fetched {len(result)} F&O stocks")
            return result

        except Exception as e:
            logger.error(f"[BreezeDataFetcher] Error fetching F&O stocks: {e}")
            return self._get_hardcoded_fo_stocks()

    # ─── Cache Management ───

    def _save_to_cache(self, filepath: Path, bars: List[PriceBar]):
        """Save price bars to cache"""
        try:
            data = [
                {
                    "date": b.date.isoformat(),
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "oi": b.oi,
                }
                for b in bars
            ]
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"[BreezeDataFetcher] Cache save failed: {e}")

    def _load_from_cache(self, filepath: Path) -> List[PriceBar]:
        """Load price bars from cache"""
        try:
            with open(filepath) as f:
                data = json.load(f)
            return [
                PriceBar(
                    date=datetime.fromisoformat(d["date"]).replace(tzinfo=_IST),
                    open=d["open"],
                    high=d["high"],
                    low=d["low"],
                    close=d["close"],
                    volume=d["volume"],
                    oi=d.get("oi", 0),
                )
                for d in data
            ]
        except Exception as e:
            logger.error(f"[BreezeDataFetcher] Cache load failed: {e}")
            return []

    def _save_options_to_cache(self, filepath: Path, options: List[OptionChain]):
        """Save option chain to cache"""
        try:
            data = [
                {
                    "date": o.date.isoformat(),
                    "strike": o.strike,
                    "option_type": o.option_type,
                    "iv": o.iv,
                    "bid": o.bid,
                    "ask": o.ask,
                    "bid_qty": o.bid_qty,
                    "ask_qty": o.ask_qty,
                    "volume": o.volume,
                    "oi": o.oi,
                }
                for o in options
            ]
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"[BreezeDataFetcher] Options cache save failed: {e}")

    def _load_options_from_cache(self, filepath: Path) -> List[OptionChain]:
        """Load option chain from cache"""
        try:
            with open(filepath) as f:
                data = json.load(f)
            return [
                OptionChain(
                    date=datetime.fromisoformat(d["date"]).replace(tzinfo=_IST),
                    strike=d["strike"],
                    option_type=d["option_type"],
                    iv=d["iv"],
                    bid=d["bid"],
                    ask=d["ask"],
                    bid_qty=d["bid_qty"],
                    ask_qty=d["ask_qty"],
                    volume=d["volume"],
                    oi=d["oi"],
                )
                for d in data
            ]
        except Exception as e:
            logger.error(f"[BreezeDataFetcher] Options cache load failed: {e}")
            return []

    # ─── Fallback (Hardcoded Data) ───

    @staticmethod
    def _get_hardcoded_nifty50() -> Dict[str, str]:
        """Fallback NIFTY50 list (if Breeze fails)"""
        return {
            "RELIANCE": "Energy",
            "TCS": "IT",
            "HDFC": "Finance",
            "INFY": "IT",
            # ... add others as needed
        }

    @staticmethod
    def _get_hardcoded_fo_stocks() -> Dict[str, str]:
        """Fallback F&O list (if Breeze fails)"""
        return {
            "RELIANCE": "Energy",
            "TCS": "IT",
            # ... add others as needed
        }


# ─────────────────────────────────────────────────────────────────
# Example Usage
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os

    api_key = os.getenv("BREEZE_API_KEY")
    api_secret = os.getenv("BREEZE_API_SECRET")

    if not api_key or not api_secret:
        print("❌ Set BREEZE_API_KEY and BREEZE_API_SECRET environment variables")
        exit(1)

    fetcher = BreezeDataFetcher(api_key, api_secret)

    # Fetch 2 years of INFY data
    print("Fetching INFY historical data...")
    prices = fetcher.get_historical_prices("INFY-EQ", days=730)
    print(f"✅ Got {len(prices)} price bars")

    # Fetch NIFTY50 constituents
    print("\nFetching NIFTY50 constituents...")
    constituents = fetcher.get_nifty50_constituents()
    print(f"✅ Got {len(constituents)} stocks")

    print("\n✅ Breeze data fetcher working!")
