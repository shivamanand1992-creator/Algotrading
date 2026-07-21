"""
Target Label Generator

For every 5-min candle, answers the supervised learning question:
"If I buy at this candle's close, does the trade reach +TARGET_PCT
before hitting -SL_PCT, within HOLD_MINUTES?"

Label = 1 (profitable) / 0 (not). Also records actual exit % and reason
so the backtester can compute true expectancy, not just accuracy.
"""

import numpy as np
import pandas as pd

TARGET_PCT = 0.8   # take profit %
SL_PCT = 0.6       # stop loss %
HOLD_MINUTES = 30  # max hold
CANDLES_AHEAD = HOLD_MINUTES // 5  # 6 candles


def label_candles(df: pd.DataFrame,
                  target_pct: float = TARGET_PCT,
                  sl_pct: float = SL_PCT,
                  candles_ahead: int = CANDLES_AHEAD) -> pd.DataFrame:
    """
    Add label columns to a feature DataFrame (single symbol, sorted by timestamp).

    Adds:
        label            : 1 if target hit before SL within window, else 0
        exit_pct         : realized % (target_pct, -sl_pct, or close-to-close)
        exit_reason      : 'target' | 'sl' | 'time' | 'eod'
    Rows within `candles_ahead` of the end of a day are labeled using whatever
    candles remain that day (no lookahead across days).
    """
    df = df.copy().reset_index(drop=True)
    n = len(df)

    entry = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    dates = df["date"].values if "date" in df.columns else pd.to_datetime(df["timestamp"]).dt.date.values

    labels = np.zeros(n, dtype=int)
    exit_pcts = np.zeros(n)
    reasons = np.empty(n, dtype=object)

    for i in range(n):
        target_price = entry[i] * (1 + target_pct / 100)
        sl_price = entry[i] * (1 - sl_pct / 100)
        label, exit_pct, reason = 0, 0.0, "time"

        last_j = i
        for j in range(i + 1, min(i + candles_ahead + 1, n)):
            if dates[j] != dates[i]:  # never look across days
                reason = "eod"
                break
            last_j = j
            # Conservative: assume SL hits first if both touched in same candle
            if lows[j] <= sl_price:
                label, exit_pct, reason = 0, -sl_pct, "sl"
                break
            if highs[j] >= target_price:
                label, exit_pct, reason = 1, target_pct, "target"
                break
        else:
            reason = "time"

        if reason in ("time", "eod"):
            if last_j > i:
                exit_pct = (closes[last_j] - entry[i]) / entry[i] * 100
                label = 1 if exit_pct > 0.15 else 0  # small positive time-exit still a win
            else:
                exit_pct, label = 0.0, 0

        labels[i] = label
        exit_pcts[i] = exit_pct
        reasons[i] = reason

    df["label"] = labels
    df["exit_pct"] = exit_pcts
    df["exit_reason"] = reasons
    return df


def expectancy_report(df: pd.DataFrame, mask=None) -> dict:
    """
    Compute expectancy metrics over labeled rows (optionally filtered by mask,
    e.g. model-selected trades only).

    Expected Profit = (Win% × Avg Win) − (Loss% × Avg Loss)
    """
    sub = df if mask is None else df[mask]
    if len(sub) == 0:
        return {"trades": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0, "expectancy": 0}

    wins = sub[sub["exit_pct"] > 0]
    losses = sub[sub["exit_pct"] <= 0]
    win_rate = len(wins) / len(sub)
    avg_win = wins["exit_pct"].mean() if len(wins) else 0.0
    avg_loss = abs(losses["exit_pct"].mean()) if len(losses) else 0.0
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    return {
        "trades": len(sub),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "expectancy": round(expectancy, 4),
        "total_pnl_pct": round(sub["exit_pct"].sum(), 2),
    }
