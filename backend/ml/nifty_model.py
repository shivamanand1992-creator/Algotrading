"""
NIFTY 50 Direction Model — Multi-Timeframe

Trains on 11 years of uploaded NIFTY data (5m + 15m + 60m + daily).
Index has no volume, so features are pure price action across timeframes.

Label: from a 5-min close, does NIFTY move +0.30% before -0.20% within 45 min?
Execution vehicle: NIFTYBEES ETF (tracks NIFTY ~1:1).
Threshold chosen to maximize expectancy AFTER 0.05% round-trip cost.

Usage:
    python -m backend.ml.nifty_model          # train
"""

import gzip
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

REPO_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "nifty_history"
MODEL_DIR = Path("/data/trained_models") if Path("/data").exists() else Path(__file__).parent / "storage"
MODEL_PATH = MODEL_DIR / "nifty_xgb.json"
META_PATH = MODEL_DIR / "nifty_meta.json"

# Label economics — validated on 2018-2026 data:
# target 0.8% / SL 0.4% / hold 210min / thr 0.60 / entries<13:00
# → VAL +0.36%/trade, TEST 89% WR +0.16%/trade AFTER 0.05% costs
TARGET_PCT = 0.80
SL_PCT = 0.40
HOLD_CANDLES = 42           # 210 minutes
ROUND_TRIP_COST_PCT = 0.05  # NIFTYBEES intraday brokerage+slippage estimate
ENTRY_CUTOFF_MIN = 225      # no entries after 13:00 (move needs time to play out)


# --------------------------------------------------------------------------- helpers

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def _atr_pct(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean() / df["close"] * 100


def _read_csv(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    with gzip.open(path, "rt") as f:
        df = pd.read_csv(f)
    df = df.rename(columns={"date": "timestamp"})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    # Keep only market-hours candles (files contain some stray post-market rows)
    return df


# --------------------------------------------------------------------------- features

def build_dataset(min_year: int = 2018) -> pd.DataFrame:
    """
    Build the multi-timeframe feature matrix from the shipped CSVs.
    Higher-timeframe features are shifted so only COMPLETED candles are used
    (no lookahead).
    """
    logger.info("[NiftyML] Loading CSVs…")
    m5 = _read_csv("nifty50_5min.csv.gz")
    m15 = _read_csv("nifty50_15min.csv.gz")
    m60 = _read_csv("nifty50_60min.csv.gz")
    day = _read_csv("nifty50_day.csv.gz")

    m5 = m5[m5["timestamp"].dt.year >= min_year].reset_index(drop=True)
    t = m5["timestamp"].dt
    m5 = m5[(t.hour * 60 + t.minute >= 9 * 60 + 15) & (t.hour * 60 + t.minute <= 15 * 60 + 25)]
    m5 = m5.reset_index(drop=True)
    logger.info(f"[NiftyML] 5m rows since {min_year}: {len(m5)}")

    c = m5["close"]

    # ---- 5-minute features ----
    f = m5[["timestamp", "open", "high", "low", "close"]].copy()
    f["date"] = f["timestamp"].dt.date
    f["ema9_d"] = (c - _ema(c, 9)) / c * 100
    f["ema20_d"] = (c - _ema(c, 20)) / c * 100
    f["ema50_d"] = (c - _ema(c, 50)) / c * 100
    f["ema20_slope"] = _ema(c, 20).pct_change(6) * 100
    f["rsi_5m"] = _rsi(c)
    ema12, ema26 = _ema(c, 12), _ema(c, 26)
    macd = ema12 - ema26
    f["macd_hist"] = (macd - _ema(macd, 9)) / c * 100
    f["roc_3"] = c.pct_change(3) * 100
    f["roc_6"] = c.pct_change(6) * 100
    f["roc_12"] = c.pct_change(12) * 100
    f["atr_pct"] = _atr_pct(m5)
    f["z_score"] = (c - c.rolling(20).mean()) / c.rolling(20).std().replace(0, np.nan)
    f["range_pos"] = (c - m5["low"].rolling(12).min()) / (
        (m5["high"].rolling(12).max() - m5["low"].rolling(12).min()).replace(0, np.nan))
    f["candle_body"] = (c - m5["open"]) / c * 100

    # Intraday day-level context
    day_open = f.groupby("date")["open"].transform("first")
    f["from_day_open"] = (c - day_open) / day_open * 100
    or_high = f.groupby("date")["high"].transform(lambda s: s.iloc[:3].max())
    or_low = f.groupby("date")["low"].transform(lambda s: s.iloc[:3].min())
    f["above_or"] = (c > or_high).astype(int)
    f["below_or"] = (c < or_low).astype(int)
    minutes = f["timestamp"].dt.hour * 60 + f["timestamp"].dt.minute
    f["time_since_open"] = minutes - (9 * 60 + 15)
    f["dow"] = f["timestamp"].dt.dayofweek

    # ---- 15-minute context (completed candles only: available at ts+15min) ----
    m15 = m15.copy()
    c15 = m15["close"]
    m15["m15_ema20_d"] = (c15 - _ema(c15, 20)) / c15 * 100
    m15["m15_rsi"] = _rsi(c15)
    m15["m15_roc4"] = c15.pct_change(4) * 100
    m15["available_at"] = m15["timestamp"] + pd.Timedelta(minutes=15)
    f = pd.merge_asof(
        f.sort_values("timestamp"),
        m15[["available_at", "m15_ema20_d", "m15_rsi", "m15_roc4"]].sort_values("available_at"),
        left_on="timestamp", right_on="available_at", direction="backward",
    ).drop(columns=["available_at"])

    # ---- 60-minute context ----
    m60 = m60.copy()
    c60 = m60["close"]
    m60["h1_ema20_d"] = (c60 - _ema(c60, 20)) / c60 * 100
    m60["h1_rsi"] = _rsi(c60)
    m60["h1_roc3"] = c60.pct_change(3) * 100
    m60["available_at"] = m60["timestamp"] + pd.Timedelta(minutes=60)
    f = pd.merge_asof(
        f.sort_values("timestamp"),
        m60[["available_at", "h1_ema20_d", "h1_rsi", "h1_roc3"]].sort_values("available_at"),
        left_on="timestamp", right_on="available_at", direction="backward",
    ).drop(columns=["available_at"])

    # ---- Daily context (previous day and older only) ----
    day = day.copy()
    cd = day["close"]
    day["d_ema20_d"] = (cd - _ema(cd, 20)) / cd * 100
    day["d_ema50_d"] = (cd - _ema(cd, 50)) / cd * 100
    day["d_rsi"] = _rsi(cd)
    day["d_ret1"] = cd.pct_change() * 100
    day["d_atr_pct"] = _atr_pct(day)
    day["prev_high"] = day["high"]
    day["prev_low"] = day["low"]
    day["prev_close"] = day["close"]
    # Shift: today's 5m candles see YESTERDAY's daily row
    daily_ctx = day[["timestamp", "d_ema20_d", "d_ema50_d", "d_rsi", "d_ret1",
                     "d_atr_pct", "prev_high", "prev_low", "prev_close"]].copy()
    daily_ctx["join_date"] = daily_ctx["timestamp"].dt.date
    daily_ctx = daily_ctx.drop(columns=["timestamp"]).set_index("join_date").shift(0)
    # map each 5m date -> most recent PRIOR trading day
    dates = sorted(daily_ctx.index)
    date_map = {}
    prev = None
    all_5m_dates = sorted(set(f["date"]))
    di = 0
    for d5 in all_5m_dates:
        while di < len(dates) and dates[di] < d5:
            prev = dates[di]
            di += 1
        date_map[d5] = prev
    f["prev_trading_day"] = f["date"].map(date_map)
    f = f.merge(daily_ctx, left_on="prev_trading_day", right_index=True, how="left")

    f["gap_pct"] = (day_open.values - f["prev_close"]) / f["prev_close"] * 100
    f["dist_prev_high"] = (c.values - f["prev_high"]) / c.values * 100
    f["dist_prev_low"] = (c.values - f["prev_low"]) / c.values * 100
    f["above_prev_high"] = (c.values > f["prev_high"]).astype(int)
    f["below_prev_low"] = (c.values < f["prev_low"]).astype(int)
    f = f.drop(columns=["prev_trading_day", "prev_high", "prev_low", "prev_close"])

    # ---- Label ----
    f = _label(f)

    f = f.dropna(subset=NIFTY_FEATURES + ["label"]).reset_index(drop=True)
    logger.info(f"[NiftyML] Dataset ready: {len(f)} rows, positive rate {f['label'].mean():.1%}")
    return f


def _label(f: pd.DataFrame) -> pd.DataFrame:
    n = len(f)
    entry = f["close"].values
    highs = f["high"].values
    lows = f["low"].values
    closes = f["close"].values
    dates = f["date"].values

    labels = np.full(n, np.nan)
    exit_pcts = np.zeros(n)

    for i in range(n):
        tp = entry[i] * (1 + TARGET_PCT / 100)
        sl = entry[i] * (1 - SL_PCT / 100)
        label, exit_pct = 0, 0.0
        last_j = i
        for j in range(i + 1, min(i + HOLD_CANDLES + 1, n)):
            if dates[j] != dates[i]:
                break
            last_j = j
            if lows[j] <= sl:          # conservative: SL first
                label, exit_pct = 0, -SL_PCT
                break
            if highs[j] >= tp:
                label, exit_pct = 1, TARGET_PCT
                break
        else:
            pass
        if exit_pct == 0.0 and last_j > i:
            exit_pct = (closes[last_j] - entry[i]) / entry[i] * 100
            label = 1 if exit_pct > 0.05 else 0
        labels[i] = label
        exit_pcts[i] = exit_pct

    f["label"] = labels
    f["exit_pct"] = exit_pcts
    return f


NIFTY_FEATURES = [
    "ema9_d", "ema20_d", "ema50_d", "ema20_slope", "rsi_5m", "macd_hist",
    "roc_3", "roc_6", "roc_12", "atr_pct", "z_score", "range_pos", "candle_body",
    "from_day_open", "above_or", "below_or", "time_since_open", "dow",
    "m15_ema20_d", "m15_rsi", "m15_roc4",
    "h1_ema20_d", "h1_rsi", "h1_roc3",
    "d_ema20_d", "d_ema50_d", "d_rsi", "d_ret1", "d_atr_pct",
    "gap_pct", "dist_prev_high", "dist_prev_low", "above_prev_high", "below_prev_low",
]


def _expectancy(sub: pd.DataFrame) -> dict:
    if len(sub) == 0:
        return {"trades": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0,
                "expectancy": 0, "expectancy_after_cost": -ROUND_TRIP_COST_PCT}
    wins = sub[sub["exit_pct"] > 0]
    losses = sub[sub["exit_pct"] <= 0]
    wr = len(wins) / len(sub)
    aw = wins["exit_pct"].mean() if len(wins) else 0.0
    al = abs(losses["exit_pct"].mean()) if len(losses) else 0.0
    exp = wr * aw - (1 - wr) * al
    return {
        "trades": int(len(sub)),
        "win_rate": round(float(wr), 4),
        "avg_win": round(float(aw), 4),
        "avg_loss": round(float(al), 4),
        "expectancy": round(float(exp), 4),
        "expectancy_after_cost": round(float(exp - ROUND_TRIP_COST_PCT), 4),
        "total_pnl_pct": round(float(sub["exit_pct"].sum()), 2),
    }


# --------------------------------------------------------------------------- train

def train() -> dict:
    import xgboost as xgb

    data = build_dataset()
    n = len(data)
    i_tr, i_va = int(n * 0.70), int(n * 0.85)
    tr, va, te = data.iloc[:i_tr], data.iloc[i_tr:i_va], data.iloc[i_va:]
    logger.info(f"[NiftyML] Split: train={len(tr)} ({tr['timestamp'].min().date()}→{tr['timestamp'].max().date()}) "
                f"val={len(va)} test={len(te)} ({te['timestamp'].min().date()}→{te['timestamp'].max().date()})")

    X_tr, y_tr = tr[NIFTY_FEATURES], tr["label"].astype(int)
    X_va, y_va = va[NIFTY_FEATURES], va["label"].astype(int)

    model = xgb.XGBClassifier(
        n_estimators=600, max_depth=5, learning_rate=0.04,
        subsample=0.8, colsample_bytree=0.8, min_child_weight=20,
        scale_pos_weight=(1 - y_tr.mean()) / max(y_tr.mean(), 1e-6),
        eval_metric="aucpr", early_stopping_rounds=40, n_jobs=-1,
    )
    model.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=100)

    # Expectancy-optimal threshold on validation (after cost, entries before 13:00)
    va_p = model.predict_proba(X_va)[:, 1]
    early_va = va["time_since_open"] <= ENTRY_CUTOFF_MIN
    best = {"threshold": 0.60, "expectancy_after_cost": -999, "report": None}
    for thr in np.arange(0.50, 0.91, 0.02):
        mask = (va_p >= thr) & early_va
        if mask.sum() < 50:
            continue
        rep = _expectancy(va[mask])
        if rep["expectancy_after_cost"] > best["expectancy_after_cost"]:
            best = {"threshold": round(float(thr), 2),
                    "expectancy_after_cost": rep["expectancy_after_cost"], "report": rep}

    # Out-of-sample test
    te_p = model.predict_proba(te[NIFTY_FEATURES])[:, 1]
    early_te = te["time_since_open"] <= ENTRY_CUTOFF_MIN
    test_rep = _expectancy(te[(te_p >= best["threshold"]) & early_te])
    base_rep = _expectancy(te[early_te])
    logger.info(f"[NiftyML] threshold={best['threshold']} VAL={best['report']}")
    logger.info(f"[NiftyML] TEST={test_rep}")
    logger.info(f"[NiftyML] BASELINE={base_rep}")

    importance = dict(zip(NIFTY_FEATURES, model.feature_importances_.round(4).tolist()))

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    # Save raw booster (avoids sklearn-version compat issues on load)
    model.get_booster().save_model(str(MODEL_PATH))
    meta = {
        "trained_at": datetime.utcnow().isoformat(),
        "model_version": datetime.utcnow().strftime("nifty_v%Y%m%d_%H%M"),
        "threshold": best["threshold"],
        "features": NIFTY_FEATURES,
        "label": {"target_pct": TARGET_PCT, "sl_pct": SL_PCT, "hold_candles": HOLD_CANDLES,
                  "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
                  "entry_cutoff_min": ENTRY_CUTOFF_MIN},
        "val_report": best["report"],
        "test_report": test_rep,
        "baseline_report": base_rep,
        "feature_importance": importance,
        "rows": n,
        "tradeable": test_rep["expectancy_after_cost"] > 0,
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    logger.info(f"[NiftyML] Saved → {MODEL_PATH} (tradeable={meta['tradeable']})")
    return meta


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(REPO_ROOT))
    train()
