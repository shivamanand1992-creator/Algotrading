"""
XGBoost Training Pipeline

Trains a binary classifier: P(trade profitable within 30 min).
Selects the probability threshold that MAXIMIZES EXPECTANCY on the
validation set — not accuracy.

Usage:
    python -m backend.ml.train_model
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from backend.ml.data_importer import DB_PATH, UNIVERSE
from backend.ml.feature_engine import compute_features, FEATURE_COLS
from backend.ml.label_generator import label_candles, expectancy_report

MODEL_DIR = Path("/data/trained_models") if Path("/data").exists() else Path(__file__).parent / "storage"
MODEL_PATH = MODEL_DIR / "ml_intraday_xgb.json"
META_PATH = MODEL_DIR / "ml_intraday_meta.json"


def load_dataset() -> pd.DataFrame:
    """Load all candles, compute features + labels per symbol."""
    conn = sqlite3.connect(DB_PATH)

    nifty = pd.read_sql(
        "SELECT * FROM index_candles_5min WHERE symbol='NIFTY50' ORDER BY timestamp", conn
    )

    frames = []
    for symbol in UNIVERSE:
        df = pd.read_sql(
            "SELECT * FROM candles_5min WHERE symbol=? ORDER BY timestamp",
            conn, params=(symbol,),
        )
        if len(df) < 200:
            continue
        try:
            feats = compute_features(df, index_df=nifty if len(nifty) else None)
            labeled = label_candles(feats)
            labeled["symbol"] = symbol
            frames.append(labeled)
        except Exception as e:
            logger.warning(f"[Train] {symbol} feature/label failed: {e}")

    conn.close()
    if not frames:
        raise RuntimeError("No training data. Run data_importer first.")

    data = pd.concat(frames, ignore_index=True)
    logger.info(f"[Train] Dataset: {len(data)} rows, {data['symbol'].nunique()} symbols, "
                f"positive rate={data['label'].mean():.1%}")
    return data


def train(data: pd.DataFrame = None) -> dict:
    """Train model, pick expectancy-optimal threshold, save artifacts."""
    import xgboost as xgb

    if data is None:
        data = load_dataset()

    data = data.sort_values("timestamp").reset_index(drop=True)
    data = data.dropna(subset=FEATURE_COLS)

    # Time-based split (NEVER random — avoids leakage): 70% train, 15% val, 15% test
    n = len(data)
    i_train, i_val = int(n * 0.70), int(n * 0.85)
    train_df, val_df, test_df = data.iloc[:i_train], data.iloc[i_train:i_val], data.iloc[i_val:]

    X_train, y_train = train_df[FEATURE_COLS], train_df["label"]
    X_val, y_val = val_df[FEATURE_COLS], val_df["label"]
    X_test = test_df[FEATURE_COLS]

    logger.info(f"[Train] train={len(train_df)} val={len(val_df)} test={len(test_df)}")

    model = xgb.XGBClassifier(
        n_estimators=400,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=10,
        scale_pos_weight=(1 - y_train.mean()) / max(y_train.mean(), 1e-6),
        eval_metric="aucpr",
        early_stopping_rounds=30,
        n_jobs=-1,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=50)

    # --- Threshold selection: maximize EXPECTANCY on validation set ---
    val_proba = model.predict_proba(X_val)[:, 1]
    best = {"threshold": 0.5, "expectancy": -999, "report": None}
    for thr in np.arange(0.50, 0.86, 0.02):
        mask = val_proba >= thr
        if mask.sum() < 30:  # need enough trades to trust the estimate
            continue
        rep = expectancy_report(val_df, mask=mask)
        if rep["expectancy"] > best["expectancy"]:
            best = {"threshold": round(float(thr), 2), "expectancy": rep["expectancy"], "report": rep}

    logger.info(f"[Train] Best threshold={best['threshold']} → val expectancy={best['expectancy']:.3f}%")
    logger.info(f"[Train] Val report: {best['report']}")

    # --- Out-of-sample test with chosen threshold ---
    test_proba = model.predict_proba(X_test)[:, 1]
    test_mask = test_proba >= best["threshold"]
    test_report = expectancy_report(test_df, mask=test_mask)
    baseline_report = expectancy_report(test_df)  # trade-everything baseline
    logger.info(f"[Train] TEST (model-selected): {test_report}")
    logger.info(f"[Train] TEST (baseline all): {baseline_report}")

    # Feature importance
    importance = dict(zip(FEATURE_COLS, model.feature_importances_.round(4).tolist()))
    top10 = sorted(importance.items(), key=lambda kv: -kv[1])[:10]
    logger.info(f"[Train] Top features: {top10}")

    # Save artifacts
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_PATH))
    meta = {
        "trained_at": datetime.utcnow().isoformat(),
        "threshold": best["threshold"],
        "feature_cols": FEATURE_COLS,
        "val_report": best["report"],
        "test_report": test_report,
        "baseline_report": baseline_report,
        "feature_importance": importance,
        "rows_train": len(train_df),
        "rows_test": len(test_df),
        "model_version": datetime.utcnow().strftime("v%Y%m%d_%H%M"),
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    logger.info(f"[Train] Model saved → {MODEL_PATH}")

    # GATE: refuse to bless a model with negative test expectancy
    if test_report["expectancy"] <= 0:
        logger.error(
            "[Train] ⚠️ TEST EXPECTANCY IS NOT POSITIVE — model saved but should NOT trade live. "
            "Stay in paper mode and collect more data."
        )
        meta["tradeable"] = False
    else:
        meta["tradeable"] = True
    META_PATH.write_text(json.dumps(meta, indent=2))

    return meta


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    train()
