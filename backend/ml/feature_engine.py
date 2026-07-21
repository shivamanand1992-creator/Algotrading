"""
Feature Engine
Calculates ~30 key features per 5-min candle for ML scoring.

Feature groups:
- Trend: EMA9/20/50, price vs EMAs, EMA alignment
- Momentum: RSI, MACD hist, ROC, ADX proxy, ATR
- Volume: relative volume, volume spike, OBV slope
- Price action: prev day high/low distance, breakout flags, opening range
- Market: NIFTY trend, index relative strength
- Patterns: inside bar, NR7, gap %
- Statistical: z-score, dist from VWAP
- Time: minutes since open
"""

import numpy as np
import pandas as pd


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def compute_features(df: pd.DataFrame, index_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Compute features for a single symbol's candle DataFrame.

    Args:
        df: DataFrame with columns [timestamp, open, high, low, close, volume],
            timestamp as datetime, sorted ascending. Should span >= 2 trading days.
        index_df: optional NIFTY candles for market-context features.

    Returns:
        DataFrame with feature columns added. Rows with insufficient history are dropped.
    """
    df = df.copy().reset_index(drop=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["timestamp"].dt.date

    c = df["close"]

    # ---- Trend ----
    df["ema9"] = _ema(c, 9)
    df["ema20"] = _ema(c, 20)
    df["ema50"] = _ema(c, 50)
    df["price_vs_ema9"] = (c - df["ema9"]) / c * 100
    df["price_vs_ema20"] = (c - df["ema20"]) / c * 100
    df["price_vs_ema50"] = (c - df["ema50"]) / c * 100
    df["ema_aligned_bull"] = ((df["ema9"] > df["ema20"]) & (df["ema20"] > df["ema50"])).astype(int)
    df["ema20_slope"] = df["ema20"].pct_change(6) * 100  # 30-min slope

    # ---- Momentum ----
    df["rsi"] = _rsi(c)
    ema12 = _ema(c, 12)
    ema26 = _ema(c, 26)
    macd = ema12 - ema26
    signal = _ema(macd, 9)
    df["macd_hist"] = macd - signal
    df["macd_hist_norm"] = df["macd_hist"] / c * 100
    df["roc_6"] = c.pct_change(6) * 100    # 30-min return
    df["roc_12"] = c.pct_change(12) * 100  # 1-hour return
    df["atr"] = _atr(df)
    df["atr_pct"] = df["atr"] / c * 100

    # ---- Volume ----
    df["volume_ma20"] = df["volume"].rolling(20).mean()
    df["rel_volume"] = df["volume"] / df["volume_ma20"].replace(0, np.nan)
    df["volume_spike"] = (df["rel_volume"] > 1.5).astype(int)
    obv = (np.sign(c.diff()) * df["volume"]).fillna(0).cumsum()
    df["obv_slope"] = obv.diff(6) / df["volume_ma20"].replace(0, np.nan)

    # ---- Per-day aggregates (prev day high/low, day open, VWAP, opening range) ----
    daily = df.groupby("date").agg(
        day_high=("high", "max"), day_low=("low", "min"),
        day_open=("open", "first"), day_close=("close", "last"),
    )
    daily["prev_high"] = daily["day_high"].shift(1)
    daily["prev_low"] = daily["day_low"].shift(1)
    daily["prev_close"] = daily["day_close"].shift(1)
    df = df.merge(daily[["prev_high", "prev_low", "prev_close"]], left_on="date", right_index=True, how="left")

    df["dist_prev_high"] = (c - df["prev_high"]) / c * 100
    df["dist_prev_low"] = (c - df["prev_low"]) / c * 100
    df["is_breakout"] = (c > df["prev_high"]).astype(int)
    df["is_breakdown"] = (c < df["prev_low"]).astype(int)
    df["gap_pct"] = df.groupby("date")["open"].transform("first") / df["prev_close"] * 100 - 100

    # VWAP (intraday, resets daily)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    df["_tpv"] = tp * df["volume"]
    df["_cum_tpv"] = df.groupby("date")["_tpv"].cumsum()
    df["_cum_vol"] = df.groupby("date")["volume"].cumsum()
    df["vwap"] = df["_cum_tpv"] / df["_cum_vol"].replace(0, np.nan)
    df["dist_vwap"] = (c - df["vwap"]) / c * 100
    df.drop(columns=["_tpv", "_cum_tpv", "_cum_vol"], inplace=True)

    # Opening range (first 3 candles = 15 min)
    or_high = df.groupby("date")["high"].transform(lambda s: s.iloc[:3].max())
    or_low = df.groupby("date")["low"].transform(lambda s: s.iloc[:3].min())
    df["above_opening_range"] = (c > or_high).astype(int)
    df["below_opening_range"] = (c < or_low).astype(int)

    # ---- Patterns ----
    df["is_inside_bar"] = ((df["high"] < df["high"].shift()) & (df["low"] > df["low"].shift())).astype(int)
    rng = df["high"] - df["low"]
    df["is_nr7"] = (rng == rng.rolling(7).min()).astype(int)
    body = (c - df["open"]).abs()
    df["is_engulfing"] = (
        (body > body.shift()) &
        (np.sign(c - df["open"]) != np.sign(c.shift() - df["open"].shift()))
    ).astype(int)

    # ---- Statistical ----
    df["z_score"] = (c - c.rolling(20).mean()) / c.rolling(20).std().replace(0, np.nan)
    df["volatility"] = c.pct_change().rolling(20).std() * 100

    # ---- Time ----
    minutes = df["timestamp"].dt.hour * 60 + df["timestamp"].dt.minute
    df["time_since_open"] = (minutes - (9 * 60 + 15)).clip(lower=0)

    # ---- Market context (NIFTY) ----
    if index_df is not None and len(index_df) > 0:
        idx = index_df.copy()
        idx["timestamp"] = pd.to_datetime(idx["timestamp"])
        idx = idx.sort_values("timestamp")
        idx["nifty_ema20"] = _ema(idx["close"], 20)
        idx["nifty_trend"] = np.sign(idx["close"] - idx["nifty_ema20"]).astype(int)
        idx["nifty_roc_6"] = idx["close"].pct_change(6) * 100
        df = pd.merge_asof(
            df.sort_values("timestamp"),
            idx[["timestamp", "nifty_trend", "nifty_roc_6"]].sort_values("timestamp"),
            on="timestamp", direction="backward",
        )
        # Relative strength: stock 30-min return minus index 30-min return
        df["rel_strength"] = df["roc_6"] - df["nifty_roc_6"]
    else:
        df["nifty_trend"] = 0
        df["nifty_roc_6"] = 0.0
        df["rel_strength"] = 0.0

    # Drop warm-up rows (need 50 candles for EMA50) and rows missing prev-day data
    df = df.dropna(subset=["ema50", "prev_high", "rel_volume", "atr"]).reset_index(drop=True)
    return df


# Canonical feature list used for training AND live scoring — keep in sync
FEATURE_COLS = [
    # Trend
    "price_vs_ema9", "price_vs_ema20", "price_vs_ema50", "ema_aligned_bull", "ema20_slope",
    # Momentum
    "rsi", "macd_hist_norm", "roc_6", "roc_12", "atr_pct",
    # Volume
    "rel_volume", "volume_spike", "obv_slope",
    # Price action
    "dist_prev_high", "dist_prev_low", "is_breakout", "is_breakdown", "gap_pct",
    "dist_vwap", "above_opening_range", "below_opening_range",
    # Patterns
    "is_inside_bar", "is_nr7", "is_engulfing",
    # Statistical
    "z_score", "volatility",
    # Time
    "time_since_open",
    # Market
    "nifty_trend", "nifty_roc_6", "rel_strength",
]
