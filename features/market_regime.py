"""
Market Regime Detection for Nifty50 Intraday Options AI Trading System.

Two complementary approaches:
  1. ``MarketRegimeDetector``    — fast, deterministic rule-based detection
     suitable for live trading.
  2. ``MarketRegimeClassifier``  — XGBoost-based probabilistic classifier
     trained on labelled historical data for higher-accuracy predictions.

Regime taxonomy
---------------
  0 → ranging        (low trend strength, range-bound price action)
  1 → trending_up    (strong bullish trend)
  2 → trending_down  (strong bearish trend)
  3 → high_volatility (elevated ATR% overrides trend classification)

Dependencies
------------
  numpy, pandas, loguru, xgboost, scikit-learn, joblib
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from loguru import logger
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore", category=UserWarning)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGIME_NAMES: dict[int, str] = {
    0: "ranging",
    1: "trending_up",
    2: "trending_down",
    3: "high_volatility",
}

REGIME_IDS: dict[str, int] = {v: k for k, v in REGIME_NAMES.items()}

# Column dependencies each module requires from TechnicalFeatureEngine
_REQUIRED_TECH_COLS = [
    "adx",
    "atr_pct",
    "ema_9",
    "ema_21",
    "rsi",
    "macd_hist",
    "bb_width",
]

_DEFAULT_MODEL_PATH = Path("trained_models/regime_model.pkl")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_columns(df: pd.DataFrame, cols: list[str], caller: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"[{caller}] Missing columns: {missing}. "
            f"Run TechnicalFeatureEngine.compute_all() first. "
            f"Available: {list(df.columns)}"
        )


def _price_slope(close: pd.Series, window: int) -> pd.Series:
    """
    Rolling linear-regression slope of *close* over *window* bars,
    normalised by the mean close price over that window (returns % slope).

    Fully vectorised via a least-squares formula for uniform x spacing:
        slope = (Σ (x - x̄)(y - ȳ)) / (Σ (x - x̄)²)
    where x = [0, 1, …, window-1].
    """
    x = np.arange(window, dtype=float)
    x_dev = x - x.mean()
    ss_xx = float((x_dev ** 2).sum())  # denominator (constant)

    def _slope(arr: np.ndarray) -> float:
        y_dev = arr - arr.mean()
        slope = np.dot(x_dev, y_dev) / ss_xx
        mean_y = arr.mean()
        return (slope / mean_y) * 100.0 if mean_y != 0 else 0.0

    return close.rolling(window=window, min_periods=window).apply(_slope, raw=True)


def _volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    """Current bar volume / rolling mean volume over *window* bars."""
    roll_mean = volume.rolling(window=window, min_periods=1).mean()
    return volume / roll_mean.replace(0, np.nan)


# ===========================================================================
# 1.  Rule-based Regime Detector
# ===========================================================================

class MarketRegimeDetector:
    """
    Deterministic, rule-based market regime classifier.

    Decision tree
    -------------
    1. ATR% > ``vol_threshold``  →  regime = 3 (high_volatility)  [highest priority]
    2. ADX  > ``adx_trend``      →  trending
       2a. EMA9 > EMA21          →  regime = 1 (trending_up)
       2b. EMA9 < EMA21          →  regime = 2 (trending_down)
    3. ADX  < ``adx_range``      →  regime = 0 (ranging)
    4. ``adx_range`` ≤ ADX ≤ ``adx_trend``  →  0 (ranging) by default

    Parameters
    ----------
    adx_trend      : ADX threshold above which the market is trending (default 25)
    adx_range      : ADX threshold below which the market is ranging (default 20)
    vol_threshold  : ATR% threshold above which regime is high-volatility (default 1.5)
    """

    def __init__(
        self,
        adx_trend: float = 25.0,
        adx_range: float = 20.0,
        vol_threshold: float = 1.5,
    ) -> None:
        self.adx_trend = adx_trend
        self.adx_range = adx_range
        self.vol_threshold = vol_threshold

    # ------------------------------------------------------------------
    # Rule-based detection
    # ------------------------------------------------------------------

    def detect_regime_rules(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Append rule-based regime columns to *df* and return the enriched copy.

        Requires columns: adx, atr_pct, ema_9, ema_21
        (produced by TechnicalFeatureEngine.compute_all())

        Adds columns
        ------------
        regime_id    : int   — 0/1/2/3
        regime_name  : str   — human-readable label
        regime_conf  : float — heuristic confidence (0.0–1.0)
                               based on how decisively the rules fire
        """
        _require_columns(df, ["adx", "atr_pct", "ema_9", "ema_21"], "detect_regime_rules")
        df = df.copy()

        adx = df["adx"].values
        atr_pct = df["atr_pct"].values
        ema9 = df["ema_9"].values
        ema21 = df["ema_21"].values

        n = len(df)
        regime_id = np.zeros(n, dtype=int)
        regime_conf = np.full(n, np.nan, dtype=float)

        for i in range(n):
            adx_v = adx[i]
            atr_v = atr_pct[i]
            e9 = ema9[i]
            e21 = ema21[i]

            if np.isnan(adx_v) or np.isnan(atr_v):
                regime_id[i] = 0  # default to ranging until indicators warm up
                regime_conf[i] = 0.0
                continue

            # Priority 1: High volatility (overrides trend)
            if atr_v > self.vol_threshold:
                regime_id[i] = 3
                # Confidence proportional to how much ATR exceeds threshold
                regime_conf[i] = float(
                    np.clip((atr_v - self.vol_threshold) / self.vol_threshold, 0, 1)
                )
                continue

            # Priority 2: Strong trend
            if adx_v > self.adx_trend:
                if not (np.isnan(e9) or np.isnan(e21)):
                    regime_id[i] = 1 if e9 > e21 else 2
                else:
                    regime_id[i] = 1  # default up when EMA not available
                # Confidence: how far ADX is above threshold (normalised ~0–1)
                regime_conf[i] = float(np.clip((adx_v - self.adx_trend) / 25.0, 0, 1))
                continue

            # Priority 3: Ranging
            regime_id[i] = 0
            # Confidence: how far ADX is below range threshold
            regime_conf[i] = float(
                np.clip((self.adx_range - adx_v) / self.adx_range, 0, 1)
                if adx_v < self.adx_range
                else 0.3   # transitional zone
            )

        df["regime_id"] = regime_id
        df["regime_name"] = pd.Categorical(
            [REGIME_NAMES[r] for r in regime_id],
            categories=list(REGIME_NAMES.values()),
        )
        df["regime_conf"] = regime_conf

        logger.debug(
            f"Rule-based regimes detected. Distribution: "
            f"{pd.Series(regime_id).value_counts().to_dict()}"
        )
        return df

    # ------------------------------------------------------------------
    # Forward-looking labels for training
    # ------------------------------------------------------------------

    def label_regimes_for_training(
        self,
        df: pd.DataFrame,
        forward_bars: int = 5,
    ) -> pd.DataFrame:
        """
        Produce forward-looking regime labels for supervised learning.

        The label for bar *t* is the **most common** regime over bars
        [t+1, t+forward_bars].  This gives the model a sense of what
        regime the market *transitions into*, which is more actionable
        than the current-bar regime.

        Requires ``detect_regime_rules`` to have been run first
        (needs the ``regime_id`` column).

        Parameters
        ----------
        df            : DataFrame with ``regime_id`` column
        forward_bars  : number of future bars to look ahead (default 5)

        Adds / updates column
        ---------------------
        regime_label  : forward-looking regime id (NaN for last forward_bars rows)
        """
        _require_columns(df, ["regime_id"], "label_regimes_for_training")
        df = df.copy()

        regime_arr = df["regime_id"].values
        n = len(regime_arr)
        labels = np.full(n, np.nan, dtype=float)

        for i in range(n - forward_bars):
            future_window = regime_arr[i + 1: i + forward_bars + 1]
            # Most frequent regime in the look-ahead window
            unique, counts = np.unique(future_window, return_counts=True)
            labels[i] = float(unique[np.argmax(counts)])

        df["regime_label"] = labels
        logger.debug(
            f"Forward labels created (forward_bars={forward_bars}). "
            f"Valid rows: {int(np.sum(~np.isnan(labels)))}/{n}"
        )
        return df

    # ------------------------------------------------------------------
    # Feature matrix for classifier
    # ------------------------------------------------------------------

    def get_regime_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Build the feature matrix *X* used by ``MarketRegimeClassifier``.

        Features
        --------
        adx, atr_pct, ema_spread, rsi, macd_hist, bb_width,
        price_slope_5, price_slope_10, volume_ratio

        Parameters
        ----------
        df : DataFrame with TechnicalFeatureEngine indicators applied

        Returns
        -------
        pd.DataFrame with exactly the 9 feature columns (no OHLCV data).
        NaN rows are *not* dropped — the caller decides how to handle them.
        """
        _require_columns(
            df,
            ["adx", "atr_pct", "ema_9", "ema_21", "rsi", "macd_hist", "bb_width", "close"],
            "get_regime_features",
        )

        feats = pd.DataFrame(index=df.index)

        feats["adx"] = df["adx"]
        feats["atr_pct"] = df["atr_pct"]
        feats["ema_spread"] = (df["ema_9"] - df["ema_21"]) / df["ema_21"].replace(0, np.nan) * 100.0
        feats["rsi"] = df["rsi"]
        feats["macd_hist"] = df["macd_hist"]
        feats["bb_width"] = df["bb_width"]
        feats["price_slope_5"] = _price_slope(df["close"], window=5)
        feats["price_slope_10"] = _price_slope(df["close"], window=10)

        if "volume" in df.columns:
            feats["volume_ratio"] = _volume_ratio(df["volume"], window=20)
        else:
            feats["volume_ratio"] = np.nan
            logger.warning(
                "get_regime_features: 'volume' column not found; "
                "volume_ratio set to NaN."
            )

        return feats


# ===========================================================================
# 2.  XGBoost Regime Classifier
# ===========================================================================

class MarketRegimeClassifier:
    """
    XGBoost-based market regime classifier.

    Workflow
    --------
    1. Generate labelled data with ``MarketRegimeDetector``
       (``detect_regime_rules`` → ``label_regimes_for_training`` →
       ``get_regime_features``).
    2. Call ``train(X, y)`` to fit the model.
    3. Call ``predict(X)`` at runtime for (label, confidence).
    4. Use ``get_current_regime(df)`` for the full pipeline in one call.

    Parameters
    ----------
    model_path : path to save / load the trained model pickle
    xgb_params : dict of XGBoost hyper-parameters (optional overrides)
    """

    _FEATURE_COLS = [
        "adx",
        "atr_pct",
        "ema_spread",
        "rsi",
        "macd_hist",
        "bb_width",
        "price_slope_5",
        "price_slope_10",
        "volume_ratio",
    ]

    def __init__(
        self,
        model_path=_DEFAULT_MODEL_PATH,
        xgb_params: Optional[dict] = None,
    ) -> None:
        # Accept either a config dict (from config.yaml ml.regime_model section)
        # or a plain path string/Path object.
        if isinstance(model_path, dict):
            cfg = model_path
            model_path = cfg.get("model_save_path", _DEFAULT_MODEL_PATH)
            if xgb_params is None:
                xgb_params = {
                    k: cfg[k]
                    for k in ("n_estimators", "max_depth", "learning_rate")
                    if k in cfg
                }
        self.model_path = Path(model_path)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)

        _default_params: dict = {
            "n_estimators": 300,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 3,
            "gamma": 0.1,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "objective": "multi:softprob",
            "num_class": 4,
            "eval_metric": "mlogloss",
            "random_state": 42,
            "n_jobs": -1,
            "use_label_encoder": False,
        }
        if xgb_params:
            _default_params.update(xgb_params)
        self._xgb_params = _default_params

        self.model: Optional[xgb.XGBClassifier] = None
        self.label_encoder: Optional[LabelEncoder] = None
        self._detector = MarketRegimeDetector()
        self._is_trained: bool = False

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        df_features: pd.DataFrame,
        df_labels: pd.Series | pd.DataFrame,
        test_size: float = 0.2,
    ) -> dict:
        """
        Train the XGBoost regime classifier.

        Parameters
        ----------
        df_features : DataFrame of shape (n_samples, 9) — output of
                      ``MarketRegimeDetector.get_regime_features()``
        df_labels   : Series / single-column DataFrame of integer regime ids
                      (0–3); NaN rows will be dropped automatically.
        test_size   : fraction of data reserved for hold-out evaluation

        Returns
        -------
        dict with training metadata (accuracy, classification_report, etc.)
        """
        logger.info("=== MarketRegimeClassifier: starting training ===")

        # Coerce labels to Series
        if isinstance(df_labels, pd.DataFrame):
            df_labels = df_labels.iloc[:, 0]

        # Align and clean
        X = df_features[self._FEATURE_COLS].copy()
        y = df_labels.copy()

        # Drop rows where either features or labels are NaN
        valid_mask = y.notna() & X.notna().all(axis=1)
        X = X[valid_mask].reset_index(drop=True)
        y = y[valid_mask].astype(int).reset_index(drop=True)

        if len(X) < 50:
            raise ValueError(
                f"Insufficient clean data for training: {len(X)} rows "
                f"(need at least 50 after NaN removal)."
            )

        logger.info(
            f"Clean training samples: {len(X)} | "
            f"Class distribution: {pd.Series(y).value_counts().to_dict()}"
        )

        # Label encoding (ensure 0-based continuous integers for XGBoost)
        self.label_encoder = LabelEncoder()
        y_enc = self.label_encoder.fit_transform(y)

        # Update num_class based on actual classes seen
        n_classes = len(self.label_encoder.classes_)
        self._xgb_params["num_class"] = n_classes

        # Time-aware train/test split (no shuffle — preserve temporal order)
        split_idx = int(len(X) * (1.0 - test_size))
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y_enc[:split_idx], y_enc[split_idx:]

        logger.info(
            f"Train: {len(X_train)} samples | Test: {len(X_test)} samples"
        )

        # Build and fit model
        self.model = xgb.XGBClassifier(**self._xgb_params)
        self.model.fit(
            X_train,
            y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        # Evaluation on hold-out set
        y_pred = self.model.predict(X_test)
        target_names = [
            REGIME_NAMES.get(int(c), str(c))
            for c in self.label_encoder.classes_
        ]
        report = classification_report(
            y_test, y_pred, target_names=target_names, zero_division=0
        )
        accuracy = float(np.mean(y_pred == y_test))

        logger.info(f"Test accuracy: {accuracy:.4f}")
        logger.info(f"Classification report:\n{report}")

        # Feature importances
        importances = dict(
            zip(self._FEATURE_COLS, self.model.feature_importances_)
        )
        sorted_imp = sorted(importances.items(), key=lambda x: x[1], reverse=True)
        logger.info(
            "Feature importances: "
            + " | ".join(f"{k}={v:.4f}" for k, v in sorted_imp)
        )

        self._is_trained = True

        # Auto-save after training
        self.save_model(self.model_path)

        meta = {
            "accuracy": accuracy,
            "classification_report": report,
            "feature_importances": importances,
            "n_train": len(X_train),
            "n_test": len(X_test),
            "n_classes": n_classes,
        }
        logger.info("=== MarketRegimeClassifier: training complete ===")
        return meta

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(
        self,
        df_features: pd.DataFrame,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Predict regime labels for a batch of feature rows.

        Parameters
        ----------
        df_features : DataFrame with columns matching ``_FEATURE_COLS``

        Returns
        -------
        regime_labels : np.ndarray of str — regime name per row
        confidence    : np.ndarray of float — max class probability per row
        """
        self._assert_trained()

        X = df_features[self._FEATURE_COLS].copy()
        # Replace NaN with column medians for robustness at inference time
        X = X.fillna(X.median())

        proba = self.model.predict_proba(X)         # (n_rows, n_classes)
        class_ids_enc = np.argmax(proba, axis=1)    # encoded class index
        confidence = proba[np.arange(len(proba)), class_ids_enc]

        # Decode back to integer regime ids → names
        class_ids = self.label_encoder.inverse_transform(class_ids_enc)
        regime_labels = np.array(
            [REGIME_NAMES.get(int(c), "unknown") for c in class_ids]
        )

        return regime_labels, confidence

    def predict_single(
        self,
        feature_row: pd.Series | dict,
    ) -> tuple[str, float]:
        """
        Predict regime for a single feature observation.

        Parameters
        ----------
        feature_row : dict or Series with feature values

        Returns
        -------
        (regime_name, confidence) — e.g. ("trending_up", 0.87)
        """
        self._assert_trained()

        if isinstance(feature_row, dict):
            feature_row = pd.Series(feature_row)

        df_single = pd.DataFrame([feature_row])[self._FEATURE_COLS]
        labels, confs = self.predict(df_single)
        return str(labels[0]), float(confs[0])

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def get_current_regime(self, df: pd.DataFrame) -> tuple[str, float]:
        """
        End-to-end regime detection for a live DataFrame.

        Pipeline
        --------
        1. Compute regime feature matrix from *df* (requires technical
           indicators to already be present in *df*).
        2. Take the **last valid row** of the feature matrix.
        3. Run XGBoost prediction.

        Parameters
        ----------
        df : DataFrame with TechnicalFeatureEngine indicators applied

        Returns
        -------
        (regime_name, confidence) — e.g. ("ranging", 0.74)

        Falls back to rule-based detection if the model is not trained.
        """
        # Compute feature matrix
        feats = self._detector.get_regime_features(df)

        # If model not loaded, use rule-based fallback
        if not self._is_trained:
            logger.warning(
                "get_current_regime: Model not trained. "
                "Falling back to rule-based detection."
            )
            df_reg = self._detector.detect_regime_rules(df)
            last_valid = df_reg["regime_id"].dropna()
            if last_valid.empty:
                return "ranging", 0.0
            rid = int(last_valid.iloc[-1])
            rconf = float(df_reg["regime_conf"].dropna().iloc[-1])
            return REGIME_NAMES.get(rid, "ranging"), rconf

        # Drop NaN rows from features, take last valid
        feats_clean = feats.dropna()
        if feats_clean.empty:
            logger.warning("get_current_regime: All feature rows are NaN.")
            return "ranging", 0.0

        last_row = feats_clean.iloc[[-1]]   # keep DataFrame shape for predict()
        labels, confs = self.predict(last_row)
        regime_name = str(labels[0])
        confidence = float(confs[0])

        logger.debug(
            f"Current regime: {regime_name} (confidence={confidence:.4f})"
        )
        return regime_name, confidence

    # ------------------------------------------------------------------
    # Model persistence
    # ------------------------------------------------------------------

    def save_model(self, path: str | Path | None = None) -> None:
        """Serialise model and label encoder to *path* via joblib."""
        self._assert_trained()
        save_path = Path(path) if path else self.model_path
        save_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "model": self.model,
            "label_encoder": self.label_encoder,
            "feature_cols": self._FEATURE_COLS,
            "xgb_params": self._xgb_params,
        }
        joblib.dump(payload, save_path, compress=3)
        logger.info(f"MarketRegimeClassifier saved to: {save_path}")

    def load_model(self, path: str | Path | None = None) -> None:
        """Deserialise model from *path*."""
        load_path = Path(path) if path else self.model_path
        if not load_path.exists():
            raise FileNotFoundError(
                f"MarketRegimeClassifier: model file not found at {load_path}"
            )

        payload = joblib.load(load_path)
        self.model = payload["model"]
        self.label_encoder = payload["label_encoder"]
        self._xgb_params = payload.get("xgb_params", self._xgb_params)
        self._is_trained = True
        logger.info(f"MarketRegimeClassifier loaded from: {load_path}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _assert_trained(self) -> None:
        if not self._is_trained or self.model is None:
            raise RuntimeError(
                "MarketRegimeClassifier: model not trained or loaded. "
                "Call train() or load_model() first."
            )

    # ------------------------------------------------------------------
    # Convenience: label entire historical DataFrame
    # ------------------------------------------------------------------

    def label_history(
        self,
        df: pd.DataFrame,
        drop_na: bool = False,
    ) -> pd.DataFrame:
        """
        Apply classifier to all rows of *df* and append regime columns.

        Useful for backtesting or post-hoc analysis.

        Adds columns
        ------------
        predicted_regime      : str  — regime name
        predicted_regime_id   : int  — regime integer id
        regime_confidence     : float — model confidence (max proba)

        Parameters
        ----------
        df       : DataFrame with TechnicalFeatureEngine indicators
        drop_na  : if True, drop rows with NaN features before labelling
        """
        feats = self._detector.get_regime_features(df)

        if drop_na:
            valid_mask = feats.notna().all(axis=1)
            feats_clean = feats[valid_mask]
        else:
            feats_clean = feats.fillna(feats.median())
            valid_mask = pd.Series(True, index=feats.index)

        labels_arr = np.full(len(df), "unknown", dtype=object)
        confs_arr = np.full(len(df), np.nan, dtype=float)

        if not feats_clean.empty:
            labels, confs = self.predict(feats_clean)
            labels_arr[valid_mask.values] = labels
            confs_arr[valid_mask.values] = confs

        df = df.copy()
        df["predicted_regime"] = labels_arr
        df["predicted_regime_id"] = [
            REGIME_IDS.get(str(r), 0) for r in labels_arr
        ]
        df["regime_confidence"] = confs_arr

        logger.debug(
            f"Historical regime labelling complete. "
            f"Distribution: {pd.Series(labels_arr).value_counts().to_dict()}"
        )
        return df
