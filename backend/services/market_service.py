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

    async def get_news_summary(self, max_items: int = 20) -> list:
        """Parse multiple Indian/global market RSS feeds and return merged headline list."""
        import xml.etree.ElementTree as ET
        import urllib.request

        # Each tuple: (url, source_label, category)
        RSS_SOURCES = [
            ("https://economictimes.indiatimes.com/markets/rss.cms",          "ET Markets",  "indian"),
            ("https://www.moneycontrol.com/rss/MCtopnews.xml",                "Moneycontrol","indian"),
            ("https://www.business-standard.com/rss/markets-106.rss",         "BS Markets",  "indian"),
            ("https://www.thehindubusinessline.com/markets/feeder/default.rss","BusinessLine","indian"),
            ("https://feeds.reuters.com/reuters/businessNews",                 "Reuters",     "global"),
            ("https://www.cnbc.com/id/10001147/device/rss/rss.html",          "CNBC",        "global"),
        ]

        def _parse_one(url: str, source: str, category: str) -> list:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; AlgotradingBot/1.0)"},
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    raw = resp.read().decode("utf-8", errors="ignore")
                root = ET.fromstring(raw)
                channel = root.find("channel")
                if channel is None:
                    return []
                news = []
                for item in channel.findall("item")[:8]:
                    title = item.findtext("title", "").strip()
                    link  = item.findtext("link", "").strip()
                    pub   = item.findtext("pubDate", "").strip()
                    if title and len(title) > 10:
                        news.append({
                            "title":    title,
                            "link":     link,
                            "published": pub[:25] if pub else "",
                            "source":   source,
                            "category": category,
                        })
                return news
            except Exception:
                return []

        def _fetch_all():
            results = []
            for url, source, cat in RSS_SOURCES:
                items = _parse_one(url, source, cat)
                results.extend(items)
                if len(results) >= max_items:
                    break
            return results[:max_items]

        try:
            items = await self._run_sync(_fetch_all)
            if items:
                logger.info(f"[News] Fetched {len(items)} headlines from RSS feeds.")
            return items
        except Exception as e:
            logger.error(f"get_news_summary error: {e}")
            return []

    # ------------------------------------------------------------------
    # Nifty daily technical indicators
    # ------------------------------------------------------------------

    async def get_nifty_technicals(self) -> dict:
        """Compute Nifty 50 daily technical indicators (EMA9/21, SMA50, RSI14, MACD, BB) from 60d daily OHLCV."""
        import yfinance as yf
        import numpy as np

        def _calc():
            df = yf.Ticker("^NSEI").history(period="90d", interval="1d")
            if df is None or df.empty or len(df) < 20:
                return {}

            closes  = df["Close"].values.astype(float)
            highs   = df["High"].values.astype(float)
            lows    = df["Low"].values.astype(float)
            volumes = df["Volume"].values.astype(float)
            n = len(closes)

            def _ema(arr, period):
                k = 2 / (period + 1)
                out = [float("nan")] * len(arr)
                if len(arr) < period:
                    return out
                out[period - 1] = float(np.mean(arr[:period]))
                for i in range(period, len(arr)):
                    out[i] = arr[i] * k + out[i - 1] * (1 - k)
                return out

            ema9_arr  = _ema(closes, 9)
            ema21_arr = _ema(closes, 21)
            ema9_val  = ema9_arr[-1]
            ema21_val = ema21_arr[-1]
            sma50_val = float(np.mean(closes[-50:])) if n >= 50 else float(np.mean(closes))

            # RSI(14) — Wilder smoothing
            deltas = np.diff(closes)
            gains  = np.where(deltas > 0, deltas, 0.0)
            losses = np.where(deltas < 0, -deltas, 0.0)
            avg_g  = float(np.mean(gains[:14]))
            avg_l  = float(np.mean(losses[:14]))
            for i in range(14, len(deltas)):
                avg_g = (avg_g * 13 + gains[i]) / 14
                avg_l = (avg_l * 13 + losses[i]) / 14
            rsi = 100.0 - (100.0 / (1 + avg_g / avg_l)) if avg_l > 0 else 100.0

            # MACD (12, 26, 9)
            ema12 = _ema(closes, 12)
            ema26 = _ema(closes, 26)
            macd_line = [
                (e12 - e26) if e12 == e12 and e26 == e26 else float("nan")
                for e12, e26 in zip(ema12, ema26)
            ]
            valid_macd = [m for m in macd_line if m == m]  # drop NaN
            sig = _ema(valid_macd, 9)
            macd_hist = valid_macd[-1] - sig[-1] if sig[-1] == sig[-1] else 0.0

            last = closes[-1]

            # Bollinger Bands (20, 2)
            sma20  = float(np.mean(closes[-20:]))
            std20  = float(np.std(closes[-20:]))
            bb_up  = sma20 + 2 * std20
            bb_lo  = sma20 - 2 * std20
            bb_pos = ((last - bb_lo) / (bb_up - bb_lo) * 100) if (bb_up - bb_lo) > 0 else 50.0

            # ATR(14)
            tr_arr = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])) for i in range(1, n)]
            atr14  = float(np.mean(tr_arr[-14:])) if len(tr_arr) >= 14 else 0.0

            # Momentum
            def pct(a, b): return round((a - b) / b * 100, 2) if b > 0 else 0.0
            mom5  = pct(closes[-1], closes[-6])  if n >= 6  else 0.0
            mom10 = pct(closes[-1], closes[-11]) if n >= 11 else 0.0
            mom20 = pct(closes[-1], closes[-21]) if n >= 21 else 0.0

            # Volume ratio (5d avg vs 20d avg)
            vol_ratio = float(np.mean(volumes[-5:])) / float(np.mean(volumes[-20:])) if n >= 20 and np.mean(volumes[-20:]) > 0 else 1.0

            # Trend
            if last > ema9_val > ema21_val:
                trend = "UPTREND"
            elif last < ema9_val < ema21_val:
                trend = "DOWNTREND"
            elif ema9_val > ema21_val:
                trend = "BULLISH BIAS"
            else:
                trend = "SIDEWAYS"

            # Overall score (0–6)
            score = 0
            if trend in ("UPTREND", "BULLISH BIAS"): score += 2
            if 45 < rsi < 70:   score += 1
            elif 70 <= rsi:      score -= 1   # overbought
            if macd_hist > 0:   score += 1
            if mom5 > 0:        score += 1
            if vol_ratio > 1.1: score += 1

            signal = "STRONG BUY" if score >= 5 else "BUY" if score >= 3 else "NEUTRAL" if score >= 1 else "CAUTION"

            # NiftyBees recommendation
            if signal in ("STRONG BUY", "BUY") and trend in ("UPTREND", "BULLISH BIAS"):
                nb_action = "ACCUMULATE"
                nb_reason = "Trend + momentum aligned. Good DCA window."
            elif trend == "DOWNTREND" and rsi < 40:
                nb_action = "DCA SLOWLY"
                nb_reason = f"Nifty in downtrend (RSI {rsi:.1f}). Small buys on each 1%+ dip."
            elif trend == "SIDEWAYS":
                nb_action = "WAIT"
                nb_reason = "Nifty ranging — wait for EMA9 > EMA21 to confirm uptrend."
            else:
                nb_action = "HOLD"
                nb_reason = "No clear signal. Monitor daily."

            # Build candle list for chart (last 45 days)
            dates = df.index.tz_convert("Asia/Kolkata") if df.index.tz else df.index
            candles = []
            for i in range(max(0, n - 45), n):
                candles.append({
                    "date":  str(dates[i].date()),
                    "close": round(float(closes[i]), 2),
                    "ema9":  round(ema9_arr[i], 2) if ema9_arr[i] == ema9_arr[i] else None,
                    "ema21": round(ema21_arr[i], 2) if ema21_arr[i] == ema21_arr[i] else None,
                    "bb_up": round(sma20 + 2 * std20, 2),
                    "bb_lo": round(sma20 - 2 * std20, 2),
                })

            return {
                "last_close":   round(float(last),      2),
                "ema9":         round(float(ema9_val),  2),
                "ema21":        round(float(ema21_val), 2),
                "sma50":        round(float(sma50_val), 2),
                "rsi14":        round(float(rsi),       1),
                "macd_hist":    round(float(macd_hist), 4),
                "atr14":        round(float(atr14),     2),
                "bb_upper":     round(float(bb_up),     2),
                "bb_lower":     round(float(bb_lo),     2),
                "bb_position":  round(float(bb_pos),    1),
                "vol_ratio":    round(float(vol_ratio), 2),
                "momentum_5d":  round(float(mom5),      2),
                "momentum_10d": round(float(mom10),     2),
                "momentum_20d": round(float(mom20),     2),
                "trend":        trend,
                "signal":       signal,
                "score":        int(score),
                "nb_action":    nb_action,
                "nb_reason":    nb_reason,
                "candles":      candles,
            }

        try:
            result = await self._run_sync(_calc)
            return result or {}
        except Exception as e:
            logger.error(f"get_nifty_technicals error: {e}")
            return {}

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
