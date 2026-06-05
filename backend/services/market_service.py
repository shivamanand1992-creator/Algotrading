import sys
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import asyncio
import pandas as pd
from loguru import logger

# Angel One's API interprets date strings as IST.  Railway runs UTC.
# Always compute "now" in IST so the date strings we send are correct.
_IST = timezone(timedelta(hours=5, minutes=30))

def _now_ist() -> datetime:
    return datetime.now(_IST).replace(tzinfo=None)

sys.path.append(str(Path(__file__).parent.parent.parent))

from backend.api.models.responses import (
    MarketDataResponse,
    OptionsChainItem,
    MarketRegimeResponse,
    PredictionResponse,
)

# Nifty50 instrument constants for Angel One
NIFTY_TOKEN    = "26000"
NIFTY_EXCHANGE = "NSE"
NIFTY_SYMBOL   = "NIFTY"


def _nearest_expiry() -> str:
    """Return the nearest Thursday expiry in DD-MMM-YYYY format (Angel One style)."""
    today = _now_ist()
    days_to_thursday = (3 - today.weekday()) % 7
    if days_to_thursday == 0 and today.hour >= 15:
        days_to_thursday = 7
    expiry = today + timedelta(days=days_to_thursday)
    return expiry.strftime("%d-%b-%Y").upper()


class MarketService:
    def __init__(self, angel_client, options_analyzer, signal_generator, config):
        self.angel_client    = angel_client
        self.options_analyzer = options_analyzer
        self.signal_generator = signal_generator
        self.config          = config
        self._cached_ltp: float = 0.0
        self._cached_prev_close: float = 0.0
        self._cache_ts: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _run_sync(self, fn, *args):
        """Run a synchronous Angel One call in the thread-pool executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    def _default_market(self) -> MarketDataResponse:
        return MarketDataResponse(
            symbol=NIFTY_SYMBOL, ltp=0.0, change=0.0,
            change_percentage=0.0, iv_percentile=50.0, pcr=1.0,
            timestamp=_now_ist(),
        )

    # ------------------------------------------------------------------
    # Current market data
    # ------------------------------------------------------------------

    async def _get_ltp_with_fallback(self) -> float:
        """Get Nifty LTP from Angel One, falling back to Yahoo Finance if session is broken."""
        if self.angel_client:
            try:
                ltp = await self._run_sync(
                    self.angel_client.get_ltp, NIFTY_EXCHANGE, NIFTY_SYMBOL, NIFTY_TOKEN
                )
                return float(ltp)
            except Exception as e:
                logger.warning(f"Angel One get_ltp failed ({e}), trying Yahoo Finance…")

        # Yahoo Finance fallback
        try:
            import yfinance as yf
            def _yf_ltp():
                t = yf.Ticker("^NSEI")
                hist = t.history(period="2d", interval="1m")
                if hist is not None and not hist.empty:
                    return float(hist["Close"].dropna().iloc[-1])
                return 0.0
            ltp = await self._run_sync(_yf_ltp)
            if ltp > 0:
                logger.debug(f"Yahoo Finance LTP fallback: {ltp:.2f}")
                return ltp
        except Exception as yf_err:
            logger.warning(f"Yahoo Finance LTP fallback failed: {yf_err}")

        # Last resort: return cached value if we have one
        return self._cached_ltp or 0.0

    async def get_current_market_data(self) -> MarketDataResponse:
        if not self.angel_client:
            return self._default_market()
        try:
            ltp: float = await self._get_ltp_with_fallback()
            if ltp == 0.0:
                return self._default_market()
            self._cached_ltp = ltp

            # Fetch previous day's close if cache is stale (>30 s)
            if (
                not self._cache_ts
                or (datetime.now(_IST) - self._cache_ts).total_seconds() > 30
            ):
                now    = _now_ist()
                f_date = (now - timedelta(days=5)).strftime("%Y-%m-%d 09:15")
                t_date = now.strftime("%Y-%m-%d %H:%M")
                prev_close_found = False

                # Try Angel One first
                try:
                    hist = await self._run_sync(
                        self.angel_client.get_historical_data,
                        NIFTY_EXCHANGE, NIFTY_TOKEN, "ONE_DAY", f_date, t_date,
                    )
                    if hist is not None and not hist.empty and len(hist) >= 2:
                        self._cached_prev_close = float(hist.iloc[-2]["close"])
                        prev_close_found = True
                    elif hist is not None and not hist.empty:
                        self._cached_prev_close = float(hist.iloc[0]["open"])
                        prev_close_found = True
                except Exception as e:
                    logger.warning(f"Angel One prev-close fetch failed: {e}")

                # Fallback: Yahoo Finance ^NSEI daily (Angel One returns nothing for spot index)
                if not prev_close_found:
                    try:
                        import yfinance as yf
                        def _yf_prev():
                            return yf.Ticker("^NSEI").history(period="5d", interval="1d")
                        yf_df = await self._run_sync(_yf_prev)
                        if yf_df is not None and not yf_df.empty:
                            closes = yf_df["Close"].dropna()
                            if len(closes) >= 2:
                                self._cached_prev_close = float(closes.iloc[-2])
                            elif len(closes) == 1:
                                self._cached_prev_close = float(closes.iloc[-1])
                            logger.debug(f"YFinance prev close: {self._cached_prev_close:.2f}")
                    except Exception as yf_err:
                        logger.warning(f"YFinance prev-close fallback failed: {yf_err}")

                self._cache_ts = datetime.now(_IST)

            prev = self._cached_prev_close if self._cached_prev_close > 0 else ltp
            change     = ltp - prev
            change_pct = (change / prev * 100) if prev > 0 else 0.0

            return MarketDataResponse(
                symbol=NIFTY_SYMBOL,
                ltp=ltp,
                change=round(change, 2),
                change_percentage=round(change_pct, 2),
                iv_percentile=45.0,
                pcr=1.0,
                timestamp=_now_ist(),
            )
        except Exception as e:
            logger.error(f"get_current_market_data error: {e}")
            return self._default_market()

    # ------------------------------------------------------------------
    # Options chain
    # ------------------------------------------------------------------

    async def get_options_chain(self) -> List[OptionsChainItem]:
        if not self.angel_client:
            return []
        try:
            ltp      = self._cached_ltp or 24500.0
            atm      = round(ltp / 50) * 50   # round to nearest 50
            expiry   = _nearest_expiry()

            raw = await self._run_sync(
                self.angel_client.get_option_chain,
                NIFTY_SYMBOL, expiry, atm, 10,
            )

            fetched = raw.get("fetched", [])
            chain_map: dict = {}
            for rec in fetched:
                strike      = int(rec.get("strikePrice", 0))
                option_type = rec.get("optionType", "").upper()
                ltp_val     = float(rec.get("ltp", 0))
                iv_val      = float(rec.get("impliedVolatility", 0))
                oi_val      = int(rec.get("openInterest", 0))
                delta       = float(rec.get("delta", 0))
                gamma       = float(rec.get("gamma", 0))
                theta       = float(rec.get("theta", 0))
                vega        = float(rec.get("vega", 0))

                if strike not in chain_map:
                    chain_map[strike] = {
                        "strike": strike,
                        "call_ltp": 0, "call_iv": 0, "call_oi": 0,
                        "call_delta": 0, "call_gamma": 0, "call_theta": 0, "call_vega": 0,
                        "put_ltp": 0,  "put_iv": 0,  "put_oi": 0,
                        "put_delta": 0, "put_gamma": 0, "put_theta": 0, "put_vega": 0,
                    }

                if option_type == "CE":
                    chain_map[strike].update(
                        call_ltp=ltp_val, call_iv=iv_val, call_oi=oi_val,
                        call_delta=delta, call_gamma=gamma, call_theta=theta, call_vega=vega,
                    )
                elif option_type == "PE":
                    chain_map[strike].update(
                        put_ltp=ltp_val, put_iv=iv_val, put_oi=oi_val,
                        put_delta=delta, put_gamma=gamma, put_theta=theta, put_vega=vega,
                    )

            return [OptionsChainItem(**v) for v in sorted(chain_map.values(), key=lambda x: x["strike"])]
        except Exception as e:
            logger.error(f"get_options_chain error: {e}")
            return []

    # ------------------------------------------------------------------
    # Market regime
    # ------------------------------------------------------------------

    async def get_market_regime(self) -> MarketRegimeResponse:
        try:
            df = await self._get_ohlcv_dataframe()
            if df.empty:
                raise ValueError("Empty OHLCV dataframe")
            loop = asyncio.get_event_loop()
            # Enrich with full feature pipeline (technical + time + VIX + daily context)
            try:
                from backend.services.strategy_service import _enrich_features
                df = await loop.run_in_executor(None, _enrich_features, df)
            except Exception as enrich_err:
                logger.warning(f"get_market_regime: feature enrichment failed: {enrich_err}")
            # Always use fresh signal generator to avoid stale reference after model reload
            from backend.dependencies import get_signal_generator
            signal_gen = get_signal_generator()
            if signal_gen is None:
                raise ValueError("Signal generator not available")
            signal = await loop.run_in_executor(None, signal_gen.generate_signal, df)
            import math
            raw_probs = signal.regime_probs or {}
            safe_probs = {k: (v if v is not None and math.isfinite(v) else 0.25) for k, v in raw_probs.items()}
            safe_conf = max(safe_probs.values()) if safe_probs else 0.5
            return MarketRegimeResponse(
                current_regime=signal.regime,
                confidence=safe_conf,
                regime_probabilities=safe_probs,
                timestamp=_now_ist(),
            )
        except Exception as e:
            logger.error(f"get_market_regime error: {e}")
            return MarketRegimeResponse(
                current_regime="ranging", confidence=0.5,
                regime_probabilities={"trending_up": 0.25, "trending_down": 0.25, "ranging": 0.35, "high_volatility": 0.15},
                timestamp=_now_ist(),
            )

    # ------------------------------------------------------------------
    # ML predictions
    # ------------------------------------------------------------------

    async def get_predictions(self) -> PredictionResponse:
        try:
            df = await self._get_ohlcv_dataframe()
            if df.empty:
                raise ValueError("Empty OHLCV dataframe")
            loop = asyncio.get_event_loop()
            # Enrich with full feature pipeline (technical + time + VIX + daily context)
            try:
                from backend.services.strategy_service import _enrich_features
                df = await loop.run_in_executor(None, _enrich_features, df)
            except Exception as enrich_err:
                logger.warning(f"get_predictions: feature enrichment failed: {enrich_err}")
            # Always use fresh signal generator to avoid stale reference after model reload
            from backend.dependencies import get_signal_generator
            signal_gen = get_signal_generator()
            if signal_gen is None:
                raise ValueError("Signal generator not available")
            signal = await loop.run_in_executor(None, signal_gen.generate_signal, df)
            direction_labels = {1: "UP", 0: "FLAT", -1: "DOWN"}
            import math
            # Sanitize NaN — Python float('nan') is not valid JSON and causes HTTP 500
            safe_conf = signal.confidence if signal.confidence is not None and math.isfinite(signal.confidence) else 0.5
            raw_probs = signal.direction_probs or {}
            safe_probs = {k: (v if v is not None and math.isfinite(v) else 1/3) for k, v in raw_probs.items()}
            if not safe_probs:
                safe_probs = {"up": 0.33, "flat": 0.34, "down": 0.33}
            return PredictionResponse(
                direction=signal.direction,
                direction_label=direction_labels.get(signal.direction, "FLAT"),
                confidence=safe_conf,
                direction_probabilities=safe_probs,
                timestamp=_now_ist(),
            )
        except Exception as e:
            logger.error(f"get_predictions error: {e}")
            return PredictionResponse(
                direction=0, direction_label="FLAT", confidence=0.5,
                direction_probabilities={"UP": 0.33, "FLAT": 0.34, "DOWN": 0.33},
                timestamp=_now_ist(),
            )

    # ------------------------------------------------------------------
    # Public: OHLCV candles for charting
    # ------------------------------------------------------------------

    async def get_ohlcv_data(self, interval: str = "FIFTEEN_MINUTE", days: int = 5) -> list:
        """Return a list of OHLCV dicts suitable for a line/candlestick chart."""
        if not self.angel_client:
            return await self._get_ohlcv_from_yfinance(interval, days)
        try:
            now    = _now_ist()
            f_date = (now - timedelta(days=days)).strftime("%Y-%m-%d 09:15")
            t_date = now.strftime("%Y-%m-%d %H:%M")
            hist   = await self._run_sync(
                self.angel_client.get_historical_data,
                NIFTY_EXCHANGE, NIFTY_TOKEN, interval, f_date, t_date,
            )
            if hist is None or hist.empty:
                logger.info("Angel One returned no OHLCV data — falling back to Yahoo Finance")
                return await self._get_ohlcv_from_yfinance(interval, days)
            hist = hist.copy()
            hist["timestamp"] = hist["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
            return hist.to_dict("records")
        except Exception as e:
            logger.error(f"get_ohlcv_data error: {e}")
            return await self._get_ohlcv_from_yfinance(interval, days)

    async def _get_ohlcv_from_yfinance(self, interval: str, days: int) -> list:
        """Fallback OHLCV from Yahoo Finance (^NSEI) when Angel One returns nothing."""
        try:
            import yfinance as yf

            _yf_map = {
                "FIVE_MINUTE":    "5m",
                "FIFTEEN_MINUTE": "15m",
                "ONE_HOUR":       "1h",
                "ONE_DAY":        "1d",
            }
            yf_interval = _yf_map.get(interval, "15m")

            # yfinance sub-hourly data is capped at 60 days
            if yf_interval in ("5m", "15m"):
                actual_days = min(days, 60)
            elif yf_interval == "1h":
                actual_days = min(days, 730)
            else:
                actual_days = days

            def _fetch():
                return yf.Ticker("^NSEI").history(
                    period=f"{actual_days}d", interval=yf_interval
                )

            df = await self._run_sync(_fetch)

            if df is None or df.empty:
                return []

            # Localise to IST and format
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
            else:
                df.index = df.index.tz_convert("Asia/Kolkata")

            df = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })
            df.index.name = "timestamp"
            df = df.reset_index()
            df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")

            keep = ["timestamp", "open", "high", "low", "close", "volume"]
            df = df[[c for c in keep if c in df.columns]]
            return df.to_dict("records")
        except Exception as e:
            logger.error(f"_get_ohlcv_from_yfinance error: {e}")
            return []

    # ------------------------------------------------------------------
    # Internal: fetch real 15-min OHLCV for model input
    # ------------------------------------------------------------------

    async def _get_ohlcv_dataframe(self) -> pd.DataFrame:
        if not self.angel_client:
            return await self._yf_ohlcv_dataframe()
        try:
            now    = _now_ist()
            f_date = (now - timedelta(days=3)).strftime("%Y-%m-%d 09:15")
            t_date = now.strftime("%Y-%m-%d %H:%M")
            hist   = await self._run_sync(
                self.angel_client.get_historical_data,
                NIFTY_EXCHANGE, NIFTY_TOKEN, "FIFTEEN_MINUTE", f_date, t_date,
            )
            if hist is None or hist.empty:
                return await self._yf_ohlcv_dataframe()
            return hist.copy()
        except Exception as e:
            logger.error(f"_get_ohlcv_dataframe error: {e}")
            return await self._yf_ohlcv_dataframe()

    async def _yf_ohlcv_dataframe(self) -> pd.DataFrame:
        """Return a 3-day 15-min OHLCV DataFrame from Yahoo Finance for signal generation."""
        try:
            import yfinance as yf

            def _fetch():
                return yf.Ticker("^NSEI").history(period="5d", interval="15m")

            df = await self._run_sync(_fetch)
            if df is None or df.empty:
                return pd.DataFrame()

            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
            else:
                df.index = df.index.tz_convert("Asia/Kolkata")

            df = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })
            df.index.name = "timestamp"
            df = df.reset_index()
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
            return df
        except Exception as e:
            logger.error(f"_yf_ohlcv_dataframe error: {e}")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Global market cues
    # ------------------------------------------------------------------

    async def get_global_cues(self) -> list:
        """Fetch last-close data for major global indices and commodities via yfinance."""
        tickers = [
            {"symbol": "^GSPC",    "name": "S&P 500",    "type": "index"},
            {"symbol": "^IXIC",    "name": "NASDAQ",     "type": "index"},
            {"symbol": "^DJI",     "name": "Dow Jones",  "type": "index"},
            {"symbol": "^N225",    "name": "Nikkei 225", "type": "index"},
            {"symbol": "^HSI",     "name": "Hang Seng",  "type": "index"},
            {"symbol": "CL=F",     "name": "Crude Oil",  "type": "commodity"},
            {"symbol": "GC=F",     "name": "Gold",       "type": "commodity"},
            {"symbol": "USDINR=X", "name": "USD/INR",    "type": "forex"},
        ]
        try:
            import yfinance as yf

            def _fetch():
                results = []
                for t in tickers:
                    try:
                        hist = yf.Ticker(t["symbol"]).history(period="2d", interval="1d")
                        if hist is None or hist.empty or len(hist) < 1:
                            results.append({**t, "ltp": None, "change": None, "change_pct": None})
                            continue
                        closes = hist["Close"].dropna()
                        ltp = float(closes.iloc[-1])
                        if len(closes) >= 2:
                            prev   = float(closes.iloc[-2])
                            change = round(ltp - prev, 4)
                            chg_pct = round((change / prev) * 100, 2) if prev else 0.0
                        else:
                            change = 0.0
                            chg_pct = 0.0
                        results.append({**t, "ltp": round(ltp, 2), "change": change, "change_pct": chg_pct})
                    except Exception:
                        results.append({**t, "ltp": None, "change": None, "change_pct": None})
                return results

            return await self._run_sync(_fetch)
        except Exception as e:
            logger.error(f"get_global_cues error: {e}")
            return []

    # ------------------------------------------------------------------
    # Market news
    # ------------------------------------------------------------------

    async def get_news_summary(self) -> list:
        """Parse ET Markets RSS feed and return headline list."""
        import xml.etree.ElementTree as ET
        RSS_URLS = [
            "https://economictimes.indiatimes.com/markets/rss.cms",
            "https://feeds.feedburner.com/etspecialssection",
        ]
        try:
            import urllib.request

            def _fetch():
                for url in RSS_URLS:
                    try:
                        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=8) as resp:
                            raw = resp.read().decode("utf-8", errors="ignore")
                        root = ET.fromstring(raw)
                        channel = root.find("channel")
                        if channel is None:
                            continue
                        items = channel.findall("item")
                        news = []
                        for item in items[:12]:
                            title = item.findtext("title", "").strip()
                            link  = item.findtext("link", "").strip()
                            pub   = item.findtext("pubDate", "").strip()
                            if title:
                                news.append({"title": title, "link": link, "published": pub})
                        if news:
                            return news
                    except Exception:
                        continue
                return []

            return await self._run_sync(_fetch)
        except Exception as e:
            logger.error(f"get_news_summary error: {e}")
            return []

    async def get_vix_data(self, interval: str = "FIFTEEN_MINUTE", days: int = 5) -> list:
        """Fetch India VIX (^INDIAVIX) data from Yahoo Finance."""
        try:
            import yfinance as yf
            _yf_map = {
                "FIVE_MINUTE":    "5m",
                "FIFTEEN_MINUTE": "15m",
                "ONE_HOUR":       "1h",
                "ONE_DAY":        "1d",
            }
            yf_interval = _yf_map.get(interval, "15m")
            actual_days = min(days, 60) if yf_interval in ("5m", "15m") else days

            def _fetch():
                return yf.Ticker("^INDIAVIX").history(
                    period=f"{actual_days}d", interval=yf_interval
                )

            df = await self._run_sync(_fetch)
            if df is None or df.empty:
                return []

            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
            else:
                df.index = df.index.tz_convert("Asia/Kolkata")

            df = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })
            df.index.name = "timestamp"
            df = df.reset_index()
            df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
            keep = ["timestamp", "open", "high", "low", "close"]
            df = df[[c for c in keep if c in df.columns]]
            return df.to_dict("records")
        except Exception as e:
            logger.error(f"get_vix_data error: {e}")
            return []
