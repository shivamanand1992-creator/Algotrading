import sys
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta
import asyncio
import pandas as pd
from loguru import logger

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
    today = datetime.now()
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
            timestamp=datetime.now(),
        )

    # ------------------------------------------------------------------
    # Current market data
    # ------------------------------------------------------------------

    async def get_current_market_data(self) -> MarketDataResponse:
        if not self.angel_client:
            return self._default_market()
        try:
            ltp: float = await self._run_sync(
                self.angel_client.get_ltp, NIFTY_EXCHANGE, NIFTY_SYMBOL, NIFTY_TOKEN
            )
            self._cached_ltp = ltp

            # Fetch previous day's close if cache is stale (>5 min)
            if (
                not self._cache_ts
                or (datetime.now() - self._cache_ts).total_seconds() > 300
            ):
                now    = datetime.now()
                f_date = (now - timedelta(days=5)).strftime("%Y-%m-%d 09:00")
                t_date = now.strftime("%Y-%m-%d %H:%M")
                try:
                    hist = await self._run_sync(
                        self.angel_client.get_historical_data,
                        NIFTY_EXCHANGE, NIFTY_TOKEN, "ONE_DAY", f_date, t_date,
                    )
                    if not hist.empty and len(hist) >= 2:
                        self._cached_prev_close = float(hist.iloc[-2]["close"])
                    elif not hist.empty and len(hist) == 1:
                        self._cached_prev_close = float(hist.iloc[0]["open"])
                    self._cache_ts = datetime.now()
                except Exception as e:
                    logger.warning(f"Historical data fetch failed: {e}")

            prev = self._cached_prev_close if self._cached_prev_close > 0 else ltp
            change     = ltp - prev
            change_pct = (change / prev * 100) if prev > 0 else 0.0

            return MarketDataResponse(
                symbol=NIFTY_SYMBOL,
                ltp=ltp,
                change=round(change, 2),
                change_percentage=round(change_pct, 2),
                iv_percentile=45.0,   # requires historical IV data; kept as placeholder
                pcr=1.0,              # requires options OI sum; updated in get_options_chain
                timestamp=datetime.now(),
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
        if not self.angel_client or not self.signal_generator:
            return MarketRegimeResponse(
                current_regime="ranging", confidence=0.5,
                regime_probabilities={"trending_up": 0.2, "trending_down": 0.2, "ranging": 0.5, "high_volatility": 0.1},
                timestamp=datetime.now(),
            )
        try:
            df = await self._get_ohlcv_dataframe()
            if df.empty:
                raise ValueError("Empty OHLCV dataframe")
            signal = await asyncio.get_event_loop().run_in_executor(
                None, self.signal_generator.generate, df
            )
            return MarketRegimeResponse(
                current_regime=signal.regime,
                confidence=max(signal.regime_probs.values()),
                regime_probabilities=signal.regime_probs,
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error(f"get_market_regime error: {e}")
            return MarketRegimeResponse(
                current_regime="ranging", confidence=0.5,
                regime_probabilities={"trending_up": 0.25, "trending_down": 0.25, "ranging": 0.35, "high_volatility": 0.15},
                timestamp=datetime.now(),
            )

    # ------------------------------------------------------------------
    # ML predictions
    # ------------------------------------------------------------------

    async def get_predictions(self) -> PredictionResponse:
        if not self.signal_generator:
            return PredictionResponse(
                direction=0, direction_label="FLAT", confidence=0.5,
                direction_probabilities={"UP": 0.33, "FLAT": 0.34, "DOWN": 0.33},
                timestamp=datetime.now(),
            )
        try:
            df = await self._get_ohlcv_dataframe()
            if df.empty:
                raise ValueError("Empty OHLCV dataframe")
            signal = await asyncio.get_event_loop().run_in_executor(
                None, self.signal_generator.generate, df
            )
            direction_labels = {1: "UP", 0: "FLAT", -1: "DOWN"}
            return PredictionResponse(
                direction=signal.direction,
                direction_label=direction_labels.get(signal.direction, "FLAT"),
                confidence=signal.confidence,
                direction_probabilities=signal.direction_probs,
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error(f"get_predictions error: {e}")
            return PredictionResponse(
                direction=0, direction_label="FLAT", confidence=0.5,
                direction_probabilities={"UP": 0.33, "FLAT": 0.34, "DOWN": 0.33},
                timestamp=datetime.now(),
            )

    # ------------------------------------------------------------------
    # Public: OHLCV candles for charting
    # ------------------------------------------------------------------

    async def get_ohlcv_data(self, interval: str = "FIFTEEN_MINUTE", days: int = 5) -> list:
        """Return a list of OHLCV dicts suitable for a line/candlestick chart."""
        if not self.angel_client:
            return []
        try:
            now    = datetime.now()
            f_date = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
            t_date = now.strftime("%Y-%m-%d %H:%M")
            hist   = await self._run_sync(
                self.angel_client.get_historical_data,
                NIFTY_EXCHANGE, NIFTY_TOKEN, interval, f_date, t_date,
            )
            if hist is None or hist.empty:
                return []
            hist = hist.copy()
            hist["timestamp"] = hist["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")
            return hist.to_dict("records")
        except Exception as e:
            logger.error(f"get_ohlcv_data error: {e}")
            return []

    # ------------------------------------------------------------------
    # Internal: fetch real 15-min OHLCV for model input
    # ------------------------------------------------------------------

    async def _get_ohlcv_dataframe(self) -> pd.DataFrame:
        if not self.angel_client:
            return pd.DataFrame()
        try:
            now    = datetime.now()
            f_date = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M")
            t_date = now.strftime("%Y-%m-%d %H:%M")
            hist   = await self._run_sync(
                self.angel_client.get_historical_data,
                NIFTY_EXCHANGE, NIFTY_TOKEN, "FIFTEEN_MINUTE", f_date, t_date,
            )
            if hist is None or hist.empty:
                return pd.DataFrame()
            df = hist.copy()
            return df
        except Exception as e:
            logger.error(f"_get_ohlcv_dataframe error: {e}")
            return pd.DataFrame()
