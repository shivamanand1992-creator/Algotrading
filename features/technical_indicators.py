"""
Technical Feature Engine for Nifty50 Intraday Options AI Trading System.

Computes a comprehensive set of technical indicators and price-action features
from OHLCV data using vectorised pandas/numpy operations.  The `ta` library is
the primary computation backend; `pandas_ta` is used as a fallback for any
indicator that `ta` does not expose.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

# ---------------------------------------------------------------------------
# Optional imports — ta is primary, pandas_ta is fallback
# ---------------------------------------------------------------------------
try:
    import ta
    _TA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TA_AVAILABLE = False
    logger.warning("'ta' library not found. Install with: pip install ta")

try:
    import pandas_ta as pta
    _PTA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PTA_AVAILABLE = False
    logger.warning("'pandas_ta' library not found. Install with: pip install pandas-ta")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_columns(df: pd.DataFrame, cols: list[str], caller: str) -> None:
    """Raise informative ValueError when required columns are missing."""
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"[{caller}] Missing columns: {missing}. Available: {list(df.columns)}")


def _safe_divide(a: pd.Series, b: pd.Series, fill: float = np.nan) -> pd.Series:
    """Element-wise division that replaces division-by-zero with *fill*."""
    return a.where(b == 0, other=a / b.replace(0, np.nan)).fillna(fill)


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class TechnicalFeatureEngine:
    """
    Computes technical analysis features for intraday OHLCV data.

    All public methods accept and return a pandas DataFrame.  The input
    DataFrame is expected to have at minimum the columns:
        open, high, low, close, volume

    Optionally it may contain a ``date`` column (or a DatetimeIndex) used to
    reset VWAP at the start of each trading session.

    Usage
    -----
    >>> engine = TechnicalFeatureEngine()
    >>> df_features = engine.compute_all(df_ohlcv)
    """

    # ------------------------------------------------------------------
    # Public: compute all features in one call
    # ------------------------------------------------------------------

    def compute_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Run every feature method and return the enriched DataFrame.

        The original DataFrame is **not** mutated; a copy is returned.
        NaN values introduced at the head of the series (warm-up periods)
        are left in place — callers should decide how to handle them
        (e.g. dropna, ffill, or pass to models that tolerate NaN).
        """
        _require_columns(df, ["open", "high", "low", "close", "volume"], "compute_all")
        df = df.copy()

        logger.debug("Computing all technical features …")

        df = self.add_ema(df)
        df = self.add_rsi(df)
        df = self.add_macd(df)
        df = self.add_bollinger_bands(df)
        df = self.add_atr(df)
        df = self.add_vwap(df)
        df = self.add_supertrend(df)
        df = self.add_stochastic(df)
        df = self.add_adx(df)
        df = self.add_obv(df)
        df = self.add_pivot_points(df)
        df = self.add_candlestick_patterns(df)
        df = self.add_price_action_features(df)
        df = self.add_support_resistance(df)

        logger.debug(f"Feature computation complete. Shape: {df.shape}")
        return df

    # ------------------------------------------------------------------
    # EMA
    # ------------------------------------------------------------------

    def add_ema(self, df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
        """
        Exponential Moving Averages.

        Adds columns: ema_9, ema_21, ema_50, ema_200
        """
        if periods is None:
            periods = [9, 21, 50, 200]

        _require_columns(df, ["close"], "add_ema")
        df = df.copy()

        close = df["close"]
        for p in periods:
            if _TA_AVAILABLE:
                df[f"ema_{p}"] = ta.trend.EMAIndicator(close=close, window=p).ema_indicator()
            else:
                df[f"ema_{p}"] = close.ewm(span=p, adjust=False).mean()

        return df

    # ------------------------------------------------------------------
    # RSI
    # ------------------------------------------------------------------

    def add_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        Relative Strength Index.

        Adds columns: rsi
        """
        _require_columns(df, ["close"], "add_rsi")
        df = df.copy()

        if _TA_AVAILABLE:
            df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=period).rsi()
        else:
            delta = df["close"].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
            avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
            rs = _safe_divide(avg_gain, avg_loss, fill=0.0)
            df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

        return df

    # ------------------------------------------------------------------
    # MACD
    # ------------------------------------------------------------------

    def add_macd(
        self,
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> pd.DataFrame:
        """
        Moving Average Convergence Divergence.

        Adds columns: macd_line, macd_signal, macd_hist
        """
        _require_columns(df, ["close"], "add_macd")
        df = df.copy()

        if _TA_AVAILABLE:
            ind = ta.trend.MACD(
                close=df["close"],
                window_fast=fast,
                window_slow=slow,
                window_sign=signal,
            )
            df["macd_line"] = ind.macd()
            df["macd_signal"] = ind.macd_signal()
            df["macd_hist"] = ind.macd_diff()
        else:
            ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
            ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
            df["macd_line"] = ema_fast - ema_slow
            df["macd_signal"] = df["macd_line"].ewm(span=signal, adjust=False).mean()
            df["macd_hist"] = df["macd_line"] - df["macd_signal"]

        return df

    # ------------------------------------------------------------------
    # Bollinger Bands
    # ------------------------------------------------------------------

    def add_bollinger_bands(
        self,
        df: pd.DataFrame,
        period: int = 20,
        std: float = 2.0,
    ) -> pd.DataFrame:
        """
        Bollinger Bands — upper, middle (SMA), lower + %B + Bandwidth.

        Adds columns: bb_upper, bb_middle, bb_lower, bb_pct_b, bb_width
        """
        _require_columns(df, ["close"], "add_bollinger_bands")
        df = df.copy()

        if _TA_AVAILABLE:
            ind = ta.volatility.BollingerBands(
                close=df["close"], window=period, window_dev=std
            )
            df["bb_upper"] = ind.bollinger_hband()
            df["bb_middle"] = ind.bollinger_mavg()
            df["bb_lower"] = ind.bollinger_lband()
            df["bb_pct_b"] = ind.bollinger_pband()
            df["bb_width"] = ind.bollinger_wband()
        else:
            rolling_mean = df["close"].rolling(window=period).mean()
            rolling_std = df["close"].rolling(window=period).std(ddof=0)
            df["bb_middle"] = rolling_mean
            df["bb_upper"] = rolling_mean + std * rolling_std
            df["bb_lower"] = rolling_mean - std * rolling_std
            band_range = df["bb_upper"] - df["bb_lower"]
            df["bb_pct_b"] = _safe_divide(df["close"] - df["bb_lower"], band_range)
            df["bb_width"] = _safe_divide(band_range, df["bb_middle"])

        return df

    # ------------------------------------------------------------------
    # ATR
    # ------------------------------------------------------------------

    def add_atr(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        Average True Range and ATR as a percentage of close.

        Adds columns: atr, atr_pct
        """
        _require_columns(df, ["high", "low", "close"], "add_atr")
        df = df.copy()

        if _TA_AVAILABLE:
            df["atr"] = ta.volatility.AverageTrueRange(
                high=df["high"], low=df["low"], close=df["close"], window=period
            ).average_true_range()
        else:
            prev_close = df["close"].shift(1)
            tr = pd.concat(
                [
                    df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            df["atr"] = tr.ewm(com=period - 1, min_periods=period).mean()

        df["atr_pct"] = _safe_divide(df["atr"], df["close"]) * 100.0
        return df

    # ------------------------------------------------------------------
    # VWAP
    # ------------------------------------------------------------------

    def add_vwap(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Volume Weighted Average Price — resets at the start of each calendar date.

        If the index is a DatetimeIndex the date is derived from it; otherwise
        the method looks for a ``date`` column.  When neither is available VWAP
        is computed without resetting (treats the whole series as one session).

        Adds columns: vwap
        """
        _require_columns(df, ["high", "low", "close", "volume"], "add_vwap")
        df = df.copy()

        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        tp_vol = typical_price * df["volume"]

        # Determine session grouping key
        if isinstance(df.index, pd.DatetimeIndex):
            date_key = df.index.normalize()
        elif "date" in df.columns:
            date_key = pd.to_datetime(df["date"]).dt.normalize()
        else:
            logger.warning(
                "add_vwap: No DatetimeIndex or 'date' column found. "
                "Computing VWAP over the entire series without session reset."
            )
            cumvol = df["volume"].cumsum()
            df["vwap"] = tp_vol.cumsum() / cumvol.replace(0, np.nan)
            return df

        df["_date_key"] = date_key
        df["_tp_vol"] = tp_vol
        df["_cum_tp_vol"] = df.groupby("_date_key")["_tp_vol"].cumsum()
        df["_cum_vol"] = df.groupby("_date_key")["volume"].cumsum()
        df["vwap"] = df["_cum_tp_vol"] / df["_cum_vol"].replace(0, np.nan)
        df.drop(columns=["_date_key", "_tp_vol", "_cum_tp_vol", "_cum_vol"], inplace=True)

        return df

    # ------------------------------------------------------------------
    # SuperTrend
    # ------------------------------------------------------------------

    def add_supertrend(
        self,
        df: pd.DataFrame,
        period: int = 10,
        multiplier: float = 3.0,
    ) -> pd.DataFrame:
        """
        SuperTrend indicator.

        Adds columns:
            supertrend        — the SuperTrend line value
            supertrend_dir    — direction: +1 (bullish) / -1 (bearish)
        """
        _require_columns(df, ["high", "low", "close"], "add_supertrend")
        df = df.copy()

        # Use pandas_ta if available — it has a clean SuperTrend implementation
        if _PTA_AVAILABLE:
            st = pta.supertrend(
                high=df["high"],
                low=df["low"],
                close=df["close"],
                length=period,
                multiplier=multiplier,
            )
            # pandas_ta returns a DataFrame; column names vary by version
            st_cols = [c for c in st.columns if "SUPERT_" in c and "d" not in c.lower() and "l" not in c.lower() and "s" not in c.lower()]
            dir_cols = [c for c in st.columns if "SUPERTd_" in c]
            if st_cols and dir_cols:
                df["supertrend"] = st[st_cols[0]].values
                df["supertrend_dir"] = st[dir_cols[0]].values
            else:
                # Fallback column name pattern
                df["supertrend"] = st.iloc[:, 0].values
                df["supertrend_dir"] = st.iloc[:, 1].values
            return df

        # Pure numpy/pandas implementation
        hl2 = (df["high"] + df["low"]) / 2.0

        # ATR via Wilder smoothing
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(com=period - 1, min_periods=period).mean()

        basic_upper = hl2 + multiplier * atr
        basic_lower = hl2 - multiplier * atr

        n = len(df)
        final_upper = np.full(n, np.nan)
        final_lower = np.full(n, np.nan)
        supertrend = np.full(n, np.nan)
        direction = np.full(n, np.nan)

        close_arr = df["close"].values
        bu_arr = basic_upper.values
        bl_arr = basic_lower.values

        for i in range(period, n):
            # Final upper band
            if np.isnan(final_upper[i - 1]):
                final_upper[i] = bu_arr[i]
            else:
                final_upper[i] = (
                    bu_arr[i]
                    if (bu_arr[i] < final_upper[i - 1] or close_arr[i - 1] > final_upper[i - 1])
                    else final_upper[i - 1]
                )

            # Final lower band
            if np.isnan(final_lower[i - 1]):
                final_lower[i] = bl_arr[i]
            else:
                final_lower[i] = (
                    bl_arr[i]
                    if (bl_arr[i] > final_lower[i - 1] or close_arr[i - 1] < final_lower[i - 1])
                    else final_lower[i - 1]
                )

            # SuperTrend value and direction
            if np.isnan(supertrend[i - 1]):
                supertrend[i] = final_upper[i]
                direction[i] = -1
            elif supertrend[i - 1] == final_upper[i - 1]:
                if close_arr[i] <= final_upper[i]:
                    supertrend[i] = final_upper[i]
                    direction[i] = -1
                else:
                    supertrend[i] = final_lower[i]
                    direction[i] = 1
            else:  # was lower band (bullish)
                if close_arr[i] >= final_lower[i]:
                    supertrend[i] = final_lower[i]
                    direction[i] = 1
                else:
                    supertrend[i] = final_upper[i]
                    direction[i] = -1

        df["supertrend"] = supertrend
        df["supertrend_dir"] = direction
        return df

    # ------------------------------------------------------------------
    # Stochastic Oscillator
    # ------------------------------------------------------------------

    def add_stochastic(
        self,
        df: pd.DataFrame,
        k: int = 14,
        d: int = 3,
    ) -> pd.DataFrame:
        """
        Stochastic Oscillator %K and %D.

        Adds columns: stoch_k, stoch_d
        """
        _require_columns(df, ["high", "low", "close"], "add_stochastic")
        df = df.copy()

        if _TA_AVAILABLE:
            ind = ta.momentum.StochasticOscillator(
                high=df["high"], low=df["low"], close=df["close"],
                window=k, smooth_window=d,
            )
            df["stoch_k"] = ind.stoch()
            df["stoch_d"] = ind.stoch_signal()
        else:
            lowest_low = df["low"].rolling(window=k).min()
            highest_high = df["high"].rolling(window=k).max()
            denom = highest_high - lowest_low
            df["stoch_k"] = _safe_divide(df["close"] - lowest_low, denom) * 100.0
            df["stoch_d"] = df["stoch_k"].rolling(window=d).mean()

        return df

    # ------------------------------------------------------------------
    # ADX
    # ------------------------------------------------------------------

    def add_adx(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        Average Directional Index along with +DI and -DI.

        Adds columns: adx, plus_di, minus_di
        """
        _require_columns(df, ["high", "low", "close"], "add_adx")
        df = df.copy()

        if _TA_AVAILABLE:
            ind = ta.trend.ADXIndicator(
                high=df["high"], low=df["low"], close=df["close"], window=period
            )
            df["adx"] = ind.adx()
            df["plus_di"] = ind.adx_pos()
            df["minus_di"] = ind.adx_neg()
        else:
            prev_high = df["high"].shift(1)
            prev_low = df["low"].shift(1)
            prev_close = df["close"].shift(1)

            plus_dm = np.where(
                (df["high"] - prev_high > prev_low - df["low"]) & (df["high"] - prev_high > 0),
                df["high"] - prev_high,
                0.0,
            )
            minus_dm = np.where(
                (prev_low - df["low"] > df["high"] - prev_high) & (prev_low - df["low"] > 0),
                prev_low - df["low"],
                0.0,
            )

            tr = pd.concat(
                [
                    df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs(),
                ],
                axis=1,
            ).max(axis=1)

            tr_s = pd.Series(tr.values, index=df.index).ewm(com=period - 1, min_periods=period).mean()
            plus_dm_s = pd.Series(plus_dm, index=df.index).ewm(com=period - 1, min_periods=period).mean()
            minus_dm_s = pd.Series(minus_dm, index=df.index).ewm(com=period - 1, min_periods=period).mean()

            df["plus_di"] = 100.0 * _safe_divide(plus_dm_s, tr_s)
            df["minus_di"] = 100.0 * _safe_divide(minus_dm_s, tr_s)

            dx = 100.0 * _safe_divide(
                (df["plus_di"] - df["minus_di"]).abs(),
                df["plus_di"] + df["minus_di"],
            )
            df["adx"] = dx.ewm(com=period - 1, min_periods=period).mean()

        return df

    # ------------------------------------------------------------------
    # OBV
    # ------------------------------------------------------------------

    def add_obv(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        On-Balance Volume.

        Adds columns: obv
        """
        _require_columns(df, ["close", "volume"], "add_obv")
        df = df.copy()

        if _TA_AVAILABLE:
            df["obv"] = ta.volume.OnBalanceVolumeIndicator(
                close=df["close"], volume=df["volume"]
            ).on_balance_volume()
        else:
            direction = np.sign(df["close"].diff().fillna(0))
            df["obv"] = (direction * df["volume"]).cumsum()

        return df

    # ------------------------------------------------------------------
    # Pivot Points
    # ------------------------------------------------------------------

    def add_pivot_points(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Classic Pivot Points computed from the *previous* bar's H/L/C.

        For intraday use the pivot is typically based on the prior session;
        here it is computed rolling bar-by-bar using lagged values so the
        feature is always available for ML models.

        Adds columns: pp, r1, r2, r3, s1, s2, s3
        """
        _require_columns(df, ["high", "low", "close"], "add_pivot_points")
        df = df.copy()

        prev_high = df["high"].shift(1)
        prev_low = df["low"].shift(1)
        prev_close = df["close"].shift(1)

        pp = (prev_high + prev_low + prev_close) / 3.0
        df["pp"] = pp
        df["r1"] = 2.0 * pp - prev_low
        df["r2"] = pp + (prev_high - prev_low)
        df["r3"] = prev_high + 2.0 * (pp - prev_low)
        df["s1"] = 2.0 * pp - prev_high
        df["s2"] = pp - (prev_high - prev_low)
        df["s3"] = prev_low - 2.0 * (prev_high - pp)

        return df

    # ------------------------------------------------------------------
    # Candlestick Patterns
    # ------------------------------------------------------------------

    def add_candlestick_patterns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Boolean flag columns for common candlestick patterns.

        Adds columns:
            pattern_doji            — small body relative to range
            pattern_hammer          — hammer (bullish reversal)
            pattern_shooting_star   — shooting star (bearish reversal)
            pattern_bull_engulfing  — bullish engulfing
            pattern_bear_engulfing  — bearish engulfing
        """
        _require_columns(df, ["open", "high", "low", "close"], "add_candlestick_patterns")
        df = df.copy()

        o = df["open"]
        h = df["high"]
        l = df["low"]
        c = df["close"]

        body = (c - o).abs()
        candle_range = h - l
        upper_wick = h - pd.concat([o, c], axis=1).max(axis=1)
        lower_wick = pd.concat([o, c], axis=1).min(axis=1) - l

        # Doji: body ≤ 10% of candle range
        small_range = candle_range < 1e-8  # avoid division by zero in tiny bars
        body_ratio = body / candle_range.where(~small_range, other=np.nan)
        df["pattern_doji"] = (body_ratio <= 0.1).astype(int)

        # Hammer: lower wick ≥ 2× body, upper wick ≤ body, appears after a decline
        hammer_cond = (
            (lower_wick >= 2.0 * body.clip(lower=1e-8))
            & (upper_wick <= body.clip(lower=1e-8))
            & (body_ratio > 0.05)
        )
        df["pattern_hammer"] = hammer_cond.astype(int)

        # Shooting Star: upper wick ≥ 2× body, lower wick ≤ body
        shooting_star_cond = (
            (upper_wick >= 2.0 * body.clip(lower=1e-8))
            & (lower_wick <= body.clip(lower=1e-8))
            & (body_ratio > 0.05)
        )
        df["pattern_shooting_star"] = shooting_star_cond.astype(int)

        # Bullish Engulfing: current bar is bullish and engulfs prior bearish bar
        prev_o = o.shift(1)
        prev_c = c.shift(1)
        bull_eng = (c > o) & (prev_c < prev_o) & (c >= prev_o) & (o <= prev_c)
        df["pattern_bull_engulfing"] = bull_eng.astype(int)

        # Bearish Engulfing: current bar is bearish and engulfs prior bullish bar
        bear_eng = (c < o) & (prev_c > prev_o) & (c <= prev_o) & (o >= prev_c)
        df["pattern_bear_engulfing"] = bear_eng.astype(int)

        return df

    # ------------------------------------------------------------------
    # Price Action Features
    # ------------------------------------------------------------------

    def add_price_action_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Derived price-action and statistical features.

        Adds columns:
            return_1        — simple 1-bar return
            return_5        — simple 5-bar return
            log_return_1    — 1-bar log return
            volatility_10   — rolling 10-bar realised volatility (std of log returns)
            volatility_20   — rolling 20-bar realised volatility
            candle_range    — high - low
            body_size       — |close - open|
            upper_wick      — upper shadow length
            lower_wick      — lower shadow length
            body_to_range   — body_size / candle_range
        """
        _require_columns(df, ["open", "high", "low", "close"], "add_price_action_features")
        df = df.copy()

        df["return_1"] = df["close"].pct_change(1)
        df["return_5"] = df["close"].pct_change(5)
        df["log_return_1"] = np.log(df["close"] / df["close"].shift(1))

        df["volatility_10"] = df["log_return_1"].rolling(10).std()
        df["volatility_20"] = df["log_return_1"].rolling(20).std()

        df["candle_range"] = df["high"] - df["low"]
        df["body_size"] = (df["close"] - df["open"]).abs()
        df["upper_wick"] = df["high"] - pd.concat([df["open"], df["close"]], axis=1).max(axis=1)
        df["lower_wick"] = pd.concat([df["open"], df["close"]], axis=1).min(axis=1) - df["low"]
        df["body_to_range"] = _safe_divide(df["body_size"], df["candle_range"])

        return df

    # ------------------------------------------------------------------
    # Support / Resistance
    # ------------------------------------------------------------------

    def add_support_resistance(self, df: pd.DataFrame, lookback: int = 20) -> pd.DataFrame:
        """
        Rolling Support and Resistance levels.

        Uses rolling min/max over the look-back window (exclusive of the
        current bar so the features are non-leaking).

        Adds columns:
            support_level       — rolling minimum low
            resistance_level    — rolling maximum high
            dist_to_support     — (close - support) / close  [%]
            dist_to_resistance  — (resistance - close) / close [%]
        """
        _require_columns(df, ["high", "low", "close"], "add_support_resistance")
        df = df.copy()

        # shift(1) to avoid look-ahead bias
        df["support_level"] = df["low"].shift(1).rolling(window=lookback).min()
        df["resistance_level"] = df["high"].shift(1).rolling(window=lookback).max()

        df["dist_to_support"] = (
            _safe_divide(df["close"] - df["support_level"], df["close"]) * 100.0
        )
        df["dist_to_resistance"] = (
            _safe_divide(df["resistance_level"] - df["close"], df["close"]) * 100.0
        )

        return df
