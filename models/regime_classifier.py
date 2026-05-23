"""
regime_classifier.py
====================
XGBoost-based Market Regime Classifier for Nifty50 intraday trading.

Classifies the current market into one of four regimes:
    trending_up      — sustained upward directional move
    trending_down    — sustained downward directional move
    ranging          — low-volatility, mean-reverting price action
    high_volatility  — elevated volatility with no clear direction

The classifier is trained on a curated feature set derived from:
  - Trend indicators  (EMA relationships, ADX, SuperTrend direction)
  - Momentum         (RSI, MACD histogram)
  - Volatility       (ATR%, Bollinger Width, realised vol)
  - Volume           (OBV trend, volume ratio)
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from loguru import logger
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import LabelEncoder, StandardScaler

# ---------------------------------------------------------------------------
# Regime labels (string ↔ int)
# ---------------------------------------------------------------------------
REGIME_LABELS: List[str] = [
    "trending_up",
    "trending_down",
    "ranging",
    "high_volatility",
]

# Features used for regime classification — must be present in the DataFrame
REGIME_FEATURE_COLS: List[str] = [
    # Trend
    "ema_9", "ema_21", "ema_50",
    "adx", "plus_di", "minus_di",
    "supertrend_dir",
    "macd_hist",
    # Momentum
    "rsi",
    "stoch_k", "stoch_d",
    # Volatility
    "atr_pct",
    "bb_width",
    "volatility_10", "volatility_20",
    # Price action
    "return_1", "return_5",
    "body_to_range",
    # Volume
    "obv",
]


def _create_regime_labels(df: pd.DataFrame) -> pd.Series:
    """
    Rule-based heuristic to auto-label regimes for training.

    Labels are derived purely from price/indicator data so we don't
    need human-annotated ground truth.

    Rules (evaluated in priority order):
    1. high_volatility  — ATR% in top 20 percentile *and* ADX >= 25
                          but the directional move is unclear
                          (|+DI - -DI| < 10)
    2. trending_up      — ADX >= 25, +DI > -DI by at least 5 pts,
                          close above EMA-21, SuperTrend direction == +1
    3. trending_down    — ADX >= 25, -DI > +DI by at least 5 pts,
                          close below EMA-21, SuperTrend direction == -1
    4. ranging          — everything else (low ADX, tight Bollinger band)

    Returns a pd.Series of string labels aligned to df.index.
    """
    required = ["adx", "plus_di", "minus_di", "close", "ema_21",
                "supertrend_dir", "atr_pct", "bb_width"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"_create_regime_labels: missing columns {missing}")

    adx = df["adx"].fillna(0)
    plus_di = df["plus_di"].fillna(0)
    minus_di = df["minus_di"].fillna(0)
    close = df["close"]
    ema21 = df["ema_21"].fillna(close)
    st_dir = df["supertrend_dir"].fillna(0)
    atr_pct = df["atr_pct"].fillna(0)
    bb_width = df["bb_width"].fillna(0)

    # Percentile thresholds computed per-series
    atr_p80 = float(np.nanpercentile(atr_pct, 80))
    bb_p30 = float(np.nanpercentile(bb_width, 30))

    n = len(df)
    labels = np.full(n, "ranging", dtype=object)

    for i in range(n):
        adx_i = adx.iloc[i]
        pdi = plus_di.iloc[i]
        mdi = minus_di.iloc[i]
        atr_i = atr_pct.iloc[i]
        bb_i = bb_width.iloc[i]
        close_i = close.iloc[i]
        ema21_i = ema21.iloc[i]
        st_i = st_dir.iloc[i]

        # High volatility: wide ATR, strong ADX but no clear direction
        if atr_i >= atr_p80 and adx_i >= 25 and abs(pdi - mdi) < 10:
            labels[i] = "high_volatility"
        # Trending up
        elif (adx_i >= 25 and pdi - mdi >= 5
              and close_i > ema21_i and st_i == 1):
            labels[i] = "trending_up"
        # Trending down
        elif (adx_i >= 25 and mdi - pdi >= 5
              and close_i < ema21_i and st_i == -1):
            labels[i] = "trending_down"
        # Ranging (fallback): low ADX or tight bands
        else:
            labels[i] = "ranging"

    return pd.Series(labels, index=df.index, name="regime")


class MarketRegimeClassifier:
    """
    XGBoost classifier that predicts the current market regime.

    Usage
    -----
    clf = MarketRegimeClassifier(config)
    clf.train(df_with_features)
    regime, confidence, probs = clf.predict(df_recent)
    clf.save()

    After loading:
    clf2 = MarketRegimeClassifier(config)
    clf2.load()
    """

    _DEFAULT_SAVE_DIR = Path("trained_models")
    _META_FILENAME = "regime_classifier_meta.pkl"
    _MODEL_FILENAME = "regime_classifier.json"

    def __init__(self, config: dict) -> None:
        """
        Parameters
        ----------
        config : dict
            Full application config.  Reads ml.regime_model sub-section.
        """
        self.config = config
        regime_cfg = config.get("ml", {}).get("regime_model", {})

        self.n_estimators: int = int(regime_cfg.get("n_estimators", 300))
        self.max_depth: int = int(regime_cfg.get("max_depth", 6))
        self.learning_rate: float = float(regime_cfg.get("learning_rate", 0.05))
        self.regimes: List[str] = regime_cfg.get("regimes", REGIME_LABELS)

        save_path = (
            config.get("ml", {})
            .get("training", {})
            .get("model_save_path", str(self._DEFAULT_SAVE_DIR))
        )
        self.save_dir = Path(save_path)
        self.save_dir.mkdir(parents=True, exist_ok=True)

        # Will be set after training / loading
        self.model: Optional[xgb.XGBClassifier] = None
        self.scaler: Optional[StandardScaler] = None
        self.label_encoder: Optional[LabelEncoder] = None
        self.feature_cols: List[str] = REGIME_FEATURE_COLS

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, df: pd.DataFrame) -> None:
        """
        Auto-label regimes and train the XGBoost classifier.

        Parameters
        ----------
        df : pd.DataFrame
            Feature-enriched OHLCV DataFrame from TechnicalFeatureEngine.
        """
        logger.info("=== MarketRegimeClassifier: starting training ===")

        # Filter feature columns that exist
        available_cols = [c for c in self.feature_cols if c in df.columns]
        missing_cols = [c for c in self.feature_cols if c not in df.columns]
        if missing_cols:
            logger.warning(
                f"Regime classifier: missing feature columns {missing_cols}. "
                "They will be excluded from training."
            )
        self.feature_cols = available_cols

        if len(self.feature_cols) == 0:
            raise ValueError(
                "No usable feature columns found in DataFrame. "
                "Run TechnicalFeatureEngine.compute_all() first."
            )

        # Auto-label
        df = df.copy()
        df["regime"] = _create_regime_labels(df)

        # Drop rows with any NaN in features
        df = df.dropna(subset=self.feature_cols + ["regime"])
        if len(df) < 100:
            raise ValueError(
                f"Insufficient training data after cleaning: {len(df)} rows."
            )

        # Encode labels
        self.label_encoder = LabelEncoder()
        self.label_encoder.fit(self.regimes)  # fit on full label set for stability
        y = self.label_encoder.transform(df["regime"].values)
        X = df[self.feature_cols].values.astype(np.float32)

        # Scale
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # Train / val split (80/20, time-ordered)
        split = int(len(y) * 0.8)
        X_train, X_val = X_scaled[:split], X_scaled[split:]
        y_train, y_val = y[:split], y[split:]

        logger.info(
            f"Regime training: {len(y_train)} train, {len(y_val)} val, "
            f"{len(self.feature_cols)} features."
        )

        # Label distribution
        unique, counts = np.unique(y_train, return_counts=True)
        dist = {
            self.label_encoder.inverse_transform([u])[0]: int(c)
            for u, c in zip(unique, counts)
        }
        logger.info(f"Regime label distribution (train): {dist}")

        # Train XGBoost
        self.model = xgb.XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            subsample=0.8,
            colsample_bytree=0.8,
            use_label_encoder=False,
            eval_metric="mlogloss",
            random_state=42,
            n_jobs=-1,
        )
        self.model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        # Evaluate
        y_pred = self.model.predict(X_val)
        acc = accuracy_score(y_val, y_pred)
        logger.info(f"Regime classifier validation accuracy: {acc:.4f}")

        target_names = [
            self.label_encoder.inverse_transform([i])[0]
            for i in range(len(self.label_encoder.classes_))
        ]
        report = classification_report(
            y_val, y_pred, target_names=target_names, zero_division=0
        )
        logger.info(f"Regime classification report:\n{report}")

        self.save()
        logger.info("=== MarketRegimeClassifier: training complete ===")

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(
        self,
        df_recent: pd.DataFrame,
    ) -> Tuple[str, float, Dict[str, float]]:
        """
        Predict the current market regime.

        Parameters
        ----------
        df_recent : pd.DataFrame
            Recent feature-enriched OHLCV data.  Only the **last row** is
            used for prediction; but the DataFrame must contain all
            feature columns.

        Returns
        -------
        regime       : str   — one of REGIME_LABELS
        confidence   : float — probability of the predicted regime
        probabilities: dict  — {regime_name: probability, ...}
        """
        if self.model is None:
            raise RuntimeError(
                "MarketRegimeClassifier not trained. Call train() or load()."
            )

        # Select and scale features from the last row
        available = [c for c in self.feature_cols if c in df_recent.columns]
        if len(available) < len(self.feature_cols):
            logger.warning(
                f"Regime predict: {len(self.feature_cols) - len(available)} "
                "feature cols missing — using available features only."
            )

        row = df_recent[available].iloc[[-1]].values.astype(np.float32)

        # Pad missing features with zeros if any columns were dropped
        if len(available) < len(self.feature_cols):
            n_missing = len(self.feature_cols) - len(available)
            row = np.hstack([row, np.zeros((1, n_missing), dtype=np.float32)])

        row_scaled = self.scaler.transform(row)
        proba = self.model.predict_proba(row_scaled)[0]  # (n_classes,)

        pred_class = int(np.argmax(proba))
        regime = str(self.label_encoder.inverse_transform([pred_class])[0])
        confidence = float(proba[pred_class])

        probabilities: Dict[str, float] = {
            str(self.label_encoder.inverse_transform([i])[0]): float(p)
            for i, p in enumerate(proba)
        }

        logger.debug(
            f"Regime: {regime} (conf={confidence:.4f}) | {probabilities}"
        )
        return regime, confidence, probabilities

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist model and preprocessing artefacts to save_dir."""
        logger.info(f"Saving MarketRegimeClassifier to {self.save_dir}")

        model_path = self.save_dir / self._MODEL_FILENAME
        self.model.save_model(str(model_path))

        meta_path = self.save_dir / self._META_FILENAME
        joblib.dump(
            {
                "scaler": self.scaler,
                "label_encoder": self.label_encoder,
                "feature_cols": self.feature_cols,
                "config": self.config,
            },
            meta_path,
        )
        logger.info("MarketRegimeClassifier saved.")

    def load(self) -> None:
        """Load model and preprocessing artefacts from save_dir."""
        logger.info(f"Loading MarketRegimeClassifier from {self.save_dir}")

        meta_path = self.save_dir / self._META_FILENAME
        if not meta_path.exists():
            raise FileNotFoundError(
                f"Regime classifier metadata not found: {meta_path}"
            )

        meta = joblib.load(meta_path)
        self.scaler = meta["scaler"]
        self.label_encoder = meta["label_encoder"]
        self.feature_cols = meta["feature_cols"]

        model_path = self.save_dir / self._MODEL_FILENAME
        if not model_path.exists():
            raise FileNotFoundError(
                f"Regime classifier model not found: {model_path}"
            )

        self.model = xgb.XGBClassifier()
        self.model.load_model(str(model_path))

        logger.info(
            f"MarketRegimeClassifier loaded. "
            f"Classes: {self.label_encoder.classes_.tolist()}"
        )
