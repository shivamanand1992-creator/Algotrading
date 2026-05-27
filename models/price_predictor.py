"""
price_predictor.py
==================
Ensemble price direction predictor for Nifty50 intraday trading.

Architecture:
  - LSTM (PyTorch)   — 40% weight
  - XGBoost          — 40% weight
  - LightGBM         — 20% weight

Predicts next-5-candle direction:
  +1  →  up   (close rises > 0.3%)
  -1  →  down (close falls > 0.3%)
   0  →  flat (otherwise)
"""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Optional, Tuple, Dict, List

import numpy as np
import pandas as pd
import joblib
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
import xgboost as xgb
import lightgbm as lgb
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, classification_report
from loguru import logger

warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------------
# Label mapping  (model outputs 0/1/2; maps to -1/0/+1)
# ---------------------------------------------------------------------------
_LABEL_TO_CLASS = {0: -1, 1: 0, 2: 1}   # model index → trading direction
_CLASS_TO_LABEL = {-1: 0, 0: 1, 1: 2}   # trading direction → model index


# =============================================================================
# LSTM Module
# =============================================================================

class LSTMModel(nn.Module):
    """
    Multi-class LSTM for price direction classification.

    Input  : (batch, seq_len, input_size)
    Output : (batch, output_size)  — raw logits for [down, flat, up]
    """

    def __init__(
        self,
        input_size: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        output_size: int = 3,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: Tensor of shape (batch, seq_len, features)
        Returns:
            Tensor of shape (batch, 3) — logits for [down, flat, up]
        """
        # h0 / c0 default to zeros
        lstm_out, _ = self.lstm(x)           # (batch, seq_len, hidden_size)
        last_hidden = lstm_out[:, -1, :]     # take last time-step
        out = self.dropout(last_hidden)
        logits = self.fc(out)                # (batch, 3)
        return logits


# =============================================================================
# Ensemble Price Direction Predictor
# =============================================================================

class PriceDirectionPredictor:
    """
    Ensemble predictor: LSTM (40%) + XGBoost (40%) + LightGBM (20%).

    Usage
    -----
    predictor = PriceDirectionPredictor(config)
    predictor.train(df, feature_cols)
    direction, confidence, probs = predictor.predict(df_recent, feature_cols)
    """

    # Prefer MODEL_SAVE_PATH env var (set in Railway to match Volume mount),
    # then fall back to an absolute path anchored at the repo root.
    _DEFAULT_SAVE_DIR = Path(
        os.getenv("MODEL_SAVE_PATH", str(Path(__file__).parent.parent / "trained_models"))
    )

    def __init__(self, config: dict):
        """
        Args:
            config: dict from config.yaml → ml.price_predictor section.
                    Expected keys (all optional, have defaults):
                      lookback_window, lstm_hidden_size, lstm_layers,
                      dropout, ensemble_weights, min_confidence,
                      model_save_path
        """
        self.config = config

        # Hyper-parameters
        self.lookback: int = config.get("lookback_window", 30)
        self.horizon: int = config.get("prediction_horizon", 5)
        self.hidden_size: int = config.get("lstm_hidden_size", 128)
        self.num_layers: int = config.get("lstm_layers", 2)
        self.dropout: float = config.get("dropout", 0.2)
        self.min_confidence: float = config.get("min_confidence", 0.65)

        weights_cfg = config.get("ensemble_weights", {})
        self.weights: Tuple[float, float, float] = (
            float(weights_cfg.get("lstm", 0.4)),
            float(weights_cfg.get("xgboost", 0.4)),
            float(weights_cfg.get("lightgbm", 0.2)),
        )

        self.save_dir = Path(
            config.get("model_save_path", str(self._DEFAULT_SAVE_DIR))
        )
        self.save_dir.mkdir(parents=True, exist_ok=True)

        # Device
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"PriceDirectionPredictor using device: {self.device}")

        # Model placeholders
        self.lstm_model: Optional[LSTMModel] = None
        self.xgb_model: Optional[xgb.XGBClassifier] = None
        self.lgbm_model: Optional[lgb.LGBMClassifier] = None
        self.scaler: Optional[StandardScaler] = None
        self.feature_cols: Optional[List[str]] = None
        self.n_features: Optional[int] = None

    # ------------------------------------------------------------------
    # Target creation
    # ------------------------------------------------------------------

    def create_target(self, df: pd.DataFrame, horizon: int = 5) -> pd.Series:
        """
        Compute forward-looking direction label.

        Returns
        -------
        pd.Series  with int values:
            +1  if close[t+horizon] > close[t] * 1.003
            -1  if close[t+horizon] < close[t] * 0.997
             0  otherwise (flat)
        """
        close = df["close"].values.astype(float)
        n = len(close)
        labels = np.zeros(n, dtype=int)

        for i in range(n - horizon):
            future_close = close[i + horizon]
            current_close = close[i]
            if future_close > current_close * 1.003:
                labels[i] = 1
            elif future_close < current_close * 0.997:
                labels[i] = -1
            else:
                labels[i] = 0

        # Last `horizon` rows get NaN (unknown future)
        series = pd.Series(labels, index=df.index, name="target")
        series.iloc[-horizon:] = np.nan
        return series

    # ------------------------------------------------------------------
    # Sequence preparation
    # ------------------------------------------------------------------

    def prepare_sequences(
        self,
        df: pd.DataFrame,
        feature_cols: List[str],
        target_col: str = "target",
        lookback: int = 30,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Build LSTM sequences and tabular feature matrix.

        Parameters
        ----------
        df          : DataFrame containing feature_cols and target_col
        feature_cols: list of feature column names
        target_col  : name of the integer target column
        lookback    : sequence length for LSTM

        Returns
        -------
        X_lstm : np.ndarray, shape (n_samples, lookback, n_features)
        X_tab  : np.ndarray, shape (n_samples, n_features)
        y      : np.ndarray, shape (n_samples,)  — label-encoded (0/1/2)
        """
        feat_arr = df[feature_cols].values.astype(float)
        target_arr = df[target_col].values.astype(float)

        # Drop rows where target is NaN
        valid_mask = ~np.isnan(target_arr)
        # We also need lookback rows available before each sample
        n_total = len(df)

        X_lstm_list: List[np.ndarray] = []
        X_tab_list: List[np.ndarray] = []
        y_list: List[int] = []

        for i in range(lookback, n_total):
            if not valid_mask[i]:
                continue
            seq = feat_arr[i - lookback: i]          # (lookback, features)
            X_lstm_list.append(seq)
            X_tab_list.append(feat_arr[i])            # latest row
            # Convert direction (-1/0/1) → class index (0/1/2)
            direction = int(target_arr[i])
            y_list.append(_CLASS_TO_LABEL[direction])

        X_lstm = np.array(X_lstm_list, dtype=np.float32)  # (n, lookback, feat)
        X_tab = np.array(X_tab_list, dtype=np.float32)    # (n, feat)
        y = np.array(y_list, dtype=int)                    # (n,)

        logger.debug(
            f"Sequences prepared: X_lstm={X_lstm.shape}, X_tab={X_tab.shape}, y={y.shape}"
        )
        return X_lstm, X_tab, y

    # ------------------------------------------------------------------
    # Training entry point
    # ------------------------------------------------------------------

    def train(self, df: pd.DataFrame, feature_cols: List[str]) -> None:
        """
        End-to-end training: creates targets, prepares sequences,
        trains all three models, logs metrics, saves to disk.

        Parameters
        ----------
        df           : DataFrame with OHLCV + feature columns
        feature_cols : list of feature column names to use for training
        """
        logger.info("=== PriceDirectionPredictor: starting training ===")
        self.feature_cols = feature_cols
        self.n_features = len(feature_cols)

        # 1. Create target
        df = df.copy()
        df["target"] = self.create_target(df, horizon=self.horizon)
        df = df.dropna(subset=["target"] + feature_cols)

        if len(df) < self.lookback + 50:
            raise ValueError(
                f"Insufficient data for training: {len(df)} rows after cleaning "
                f"(need at least {self.lookback + 50})."
            )

        # 2. Scale features
        self.scaler = StandardScaler()
        df[feature_cols] = self.scaler.fit_transform(df[feature_cols])

        # 3. Build sequences
        X_lstm, X_tab, y = self.prepare_sequences(
            df, feature_cols, "target", self.lookback
        )

        # 4. Train/val split (80/20, time-ordered)
        split_idx = int(len(y) * 0.8)
        X_lstm_train, X_lstm_val = X_lstm[:split_idx], X_lstm[split_idx:]
        X_tab_train, X_tab_val = X_tab[:split_idx], X_tab[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        logger.info(
            f"Train samples: {len(y_train)}, Val samples: {len(y_val)}, "
            f"Features: {self.n_features}"
        )

        # 5. Train individual models
        self._train_lstm(X_lstm_train, y_train, X_lstm_val, y_val)
        self._train_xgb(X_tab_train, y_train)
        self._train_lgbm(X_tab_train, y_train)

        # 6. Evaluate ensemble on validation set
        logger.info("--- Evaluating ensemble on validation set ---")
        self._evaluate_ensemble(X_lstm_val, X_tab_val, y_val)

        # 7. Save everything
        self.save()
        logger.info("=== PriceDirectionPredictor: training complete ===")

    # ------------------------------------------------------------------
    # Individual model trainers
    # ------------------------------------------------------------------

    def _train_lstm(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        epochs: int = 50,
        batch_size: int = 32,
    ) -> None:
        """Train the LSTM model with Adam + CrossEntropy + early stopping."""
        logger.info(f"Training LSTM: epochs={epochs}, batch_size={batch_size}")

        n_features = X_train.shape[2]
        self.lstm_model = LSTMModel(
            input_size=n_features,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            output_size=3,
            dropout=self.dropout,
        ).to(self.device)

        # DataLoaders
        X_t = torch.tensor(X_train, dtype=torch.float32)
        y_t = torch.tensor(y_train, dtype=torch.long)
        train_ds = TensorDataset(X_t, y_t)
        train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)

        has_val = X_val is not None and y_val is not None
        if has_val:
            X_v = torch.tensor(X_val, dtype=torch.float32)
            y_v = torch.tensor(y_val, dtype=torch.long)
            val_ds = TensorDataset(X_v, y_v)
            val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

        optimizer = torch.optim.Adam(self.lstm_model.parameters(), lr=1e-3)
        criterion = nn.CrossEntropyLoss()
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", patience=5, factor=0.5
        )

        # Early stopping state
        best_val_loss = float("inf")
        patience_counter = 0
        early_stop_patience = 10
        best_state_dict = None

        for epoch in range(1, epochs + 1):
            self.lstm_model.train()
            train_loss = 0.0
            for X_batch, y_batch in train_loader:
                X_batch = X_batch.to(self.device)
                y_batch = y_batch.to(self.device)

                optimizer.zero_grad()
                logits = self.lstm_model(X_batch)
                loss = criterion(logits, y_batch)
                loss.backward()
                nn.utils.clip_grad_norm_(self.lstm_model.parameters(), 1.0)
                optimizer.step()
                train_loss += loss.item() * len(y_batch)

            train_loss /= len(y_train)

            # Validation step
            if has_val:
                self.lstm_model.eval()
                val_loss = 0.0
                with torch.no_grad():
                    for X_batch, y_batch in val_loader:
                        X_batch = X_batch.to(self.device)
                        y_batch = y_batch.to(self.device)
                        logits = self.lstm_model(X_batch)
                        loss = criterion(logits, y_batch)
                        val_loss += loss.item() * len(y_batch)
                val_loss /= len(y_val)
                scheduler.step(val_loss)

                if epoch % 10 == 0:
                    logger.debug(
                        f"LSTM Epoch {epoch}/{epochs} — "
                        f"train_loss={train_loss:.4f}, val_loss={val_loss:.4f}"
                    )

                # Early stopping
                if val_loss < best_val_loss - 1e-4:
                    best_val_loss = val_loss
                    patience_counter = 0
                    best_state_dict = {
                        k: v.cpu().clone()
                        for k, v in self.lstm_model.state_dict().items()
                    }
                else:
                    patience_counter += 1
                    if patience_counter >= early_stop_patience:
                        logger.info(
                            f"LSTM early stopping at epoch {epoch} "
                            f"(best_val_loss={best_val_loss:.4f})"
                        )
                        break
            else:
                if epoch % 10 == 0:
                    logger.debug(
                        f"LSTM Epoch {epoch}/{epochs} — train_loss={train_loss:.4f}"
                    )

        # Restore best weights
        if best_state_dict is not None:
            self.lstm_model.load_state_dict(best_state_dict)

        self.lstm_model.eval()
        logger.info("LSTM training complete.")

    @staticmethod
    def _ensure_all_classes(
        X: np.ndarray, y: np.ndarray, n_classes: int = 3
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Guarantee that labels 0..n_classes-1 all appear in y.

        XGBoost ≥ 2.x and LightGBM require contiguous integer labels
        starting at 0.  If some classes are missing from the training
        split (e.g. all samples are flat), we add phantom rows using the
        column-wise mean feature values so the model can compile.

        Parameters
        ----------
        X         : (n_samples, n_features)
        y         : (n_samples,) — label-encoded, values in {0, 1, 2}
        n_classes : int — total number of classes (3 for price direction)

        Returns
        -------
        X_out, y_out  — with any missing class labels appended
        """
        present = set(np.unique(y))
        missing = sorted(set(range(n_classes)) - present)
        if not missing:
            return X, y
        phantom_X = np.tile(X.mean(axis=0), (len(missing), 1)).astype(X.dtype)
        phantom_y = np.array(missing, dtype=y.dtype)
        return np.vstack([X, phantom_X]), np.concatenate([y, phantom_y])

    def _train_xgb(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train XGBoost classifier on tabular features."""
        logger.info("Training XGBoost classifier …")

        # Ensure all 3 class labels are present (required by XGBoost ≥ 2.x)
        X_fit, y_fit = self._ensure_all_classes(X, y, n_classes=3)

        self.xgb_model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="mlogloss",
            num_class=3,
            objective="multi:softprob",
            random_state=42,
            n_jobs=-1,
        )
        self.xgb_model.fit(X_fit, y_fit)
        train_acc = accuracy_score(y, self.xgb_model.predict(X))
        logger.info(f"XGBoost train accuracy: {train_acc:.4f}")

    def _train_lgbm(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train LightGBM classifier on tabular features."""
        logger.info("Training LightGBM classifier …")

        # Ensure all 3 class labels are present (required by LightGBM)
        X_fit, y_fit = self._ensure_all_classes(X, y, n_classes=3)

        self.lgbm_model = lgb.LGBMClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            num_class=3,
            verbose=-1,
        )
        self.lgbm_model.fit(X_fit, y_fit)
        train_acc = accuracy_score(y, self.lgbm_model.predict(X))
        logger.info(f"LightGBM train accuracy: {train_acc:.4f}")

    # ------------------------------------------------------------------
    # Ensemble logic
    # ------------------------------------------------------------------

    def _ensemble_predict(
        self,
        lstm_probs: np.ndarray,
        xgb_probs: np.ndarray,
        lgbm_probs: np.ndarray,
        weights: Tuple[float, float, float] = (0.4, 0.4, 0.2),
    ) -> np.ndarray:
        """
        Weighted average of three probability arrays.

        All inputs shape: (n_samples, 3) — columns are [down, flat, up].
        Returns combined probabilities (n_samples, 3).
        """
        w_lstm, w_xgb, w_lgbm = weights
        total = w_lstm + w_xgb + w_lgbm
        combined = (
            w_lstm * lstm_probs
            + w_xgb * xgb_probs
            + w_lgbm * lgbm_probs
        ) / total
        return combined

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(
        self,
        df_recent: pd.DataFrame,
        feature_cols: List[str],
    ) -> Tuple[int, float, Dict[str, float]]:
        """
        Predict the next 5-candle price direction.

        Parameters
        ----------
        df_recent    : recent OHLCV + feature DataFrame (at least `lookback` rows)
        feature_cols : same feature columns used during training

        Returns
        -------
        direction    : int — +1 (up), -1 (down), 0 (flat)
        confidence   : float — max probability from ensemble
        probabilities: dict — {'down': p, 'flat': p, 'up': p}
        """
        if self.lstm_model is None or self.xgb_model is None or self.lgbm_model is None:
            raise RuntimeError("Models not trained. Call train() or load() first.")

        if len(df_recent) < self.lookback:
            raise ValueError(
                f"Need at least {self.lookback} rows, got {len(df_recent)}."
            )

        df_proc = df_recent.copy()

        # Replace NaN/Inf in features before scaling to prevent NaN propagation
        df_proc[feature_cols] = df_proc[feature_cols].replace(
            [np.inf, -np.inf], np.nan
        ).fillna(0.0)

        # Scale features with trained scaler
        df_proc[feature_cols] = self.scaler.transform(df_proc[feature_cols])
        feat_arr = df_proc[feature_cols].values.astype(np.float32)
        # Final NaN guard after scaling
        feat_arr = np.nan_to_num(feat_arr, nan=0.0, posinf=0.0, neginf=0.0)

        # Take the last `lookback` rows
        seq = feat_arr[-self.lookback:]          # (lookback, features)
        tab = feat_arr[-1:]                      # (1, features)

        # --- LSTM ---
        self.lstm_model.eval()
        with torch.no_grad():
            x_tensor = torch.tensor(seq[np.newaxis, ...], dtype=torch.float32).to(
                self.device
            )
            logits = self.lstm_model(x_tensor)   # (1, 3)
            lstm_probs = torch.softmax(logits, dim=-1).cpu().numpy()  # (1, 3)

        # --- XGBoost ---
        xgb_probs = self.xgb_model.predict_proba(tab)   # (1, 3)

        # --- LightGBM ---
        lgbm_probs = self.lgbm_model.predict_proba(tab)  # (1, 3)

        # --- Ensemble ---
        combined = self._ensemble_predict(
            lstm_probs, xgb_probs, lgbm_probs, self.weights
        )  # (1, 3)
        probs = combined[0]  # shape (3,)

        # Sanitize NaN/Inf from ensemble output (can occur when LSTM receives all-zero inputs)
        if not np.all(np.isfinite(probs)):
            logger.warning(
                "price_predictor: NaN/Inf in ensemble probs — falling back to uniform distribution"
            )
            probs = np.array([1 / 3, 1 / 3, 1 / 3], dtype=np.float32)

        # Predicted class index (0=down, 1=flat, 2=up)
        pred_class = int(np.argmax(probs))
        direction = _LABEL_TO_CLASS[pred_class]
        confidence = float(probs[pred_class])

        probabilities = {
            "down": float(probs[0]),
            "flat": float(probs[1]),
            "up": float(probs[2]),
        }

        logger.debug(
            f"Prediction: direction={direction}, confidence={confidence:.4f}, "
            f"probs={probabilities}"
        )
        return direction, confidence, probabilities

    # ------------------------------------------------------------------
    # Evaluation helper
    # ------------------------------------------------------------------

    def _evaluate_ensemble(
        self,
        X_lstm: np.ndarray,
        X_tab: np.ndarray,
        y: np.ndarray,
    ) -> None:
        """Run ensemble on held-out data and log accuracy + classification report."""
        self.lstm_model.eval()
        batch_size = 64

        lstm_probs_list: List[np.ndarray] = []
        with torch.no_grad():
            for start in range(0, len(X_lstm), batch_size):
                end = start + batch_size
                x_batch = torch.tensor(
                    X_lstm[start:end], dtype=torch.float32
                ).to(self.device)
                logits = self.lstm_model(x_batch)
                probs = torch.softmax(logits, dim=-1).cpu().numpy()
                lstm_probs_list.append(probs)
        lstm_probs_all = np.vstack(lstm_probs_list)

        xgb_probs_all = self.xgb_model.predict_proba(X_tab)
        lgbm_probs_all = self.lgbm_model.predict_proba(X_tab)

        combined = self._ensemble_predict(
            lstm_probs_all, xgb_probs_all, lgbm_probs_all, self.weights
        )
        preds = np.argmax(combined, axis=1)

        acc = accuracy_score(y, preds)
        logger.info(f"Ensemble validation accuracy: {acc:.4f}")
        # labels=[0,1,2] ensures report covers all classes even when some
        # are absent from the validation split (small datasets).
        report = classification_report(
            y, preds,
            labels=[0, 1, 2],
            target_names=["down", "flat", "up"],
            zero_division=0,
        )
        logger.info(f"Classification report:\n{report}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Save all model artefacts to save_dir."""
        logger.info(f"Saving PriceDirectionPredictor to {self.save_dir}")

        # LSTM weights
        lstm_path = self.save_dir / "lstm_model.pt"
        torch.save(
            {
                "state_dict": self.lstm_model.state_dict(),
                "input_size": self.n_features,
                "hidden_size": self.hidden_size,
                "num_layers": self.num_layers,
                "output_size": 3,
                "dropout": self.dropout,
            },
            lstm_path,
        )

        # XGBoost
        xgb_path = self.save_dir / "xgb_price_predictor.json"
        self.xgb_model.save_model(str(xgb_path))

        # LightGBM — persist the full sklearn wrapper with joblib so we
        # can restore predict_proba without re-fitting.
        lgbm_path = self.save_dir / "lgbm_price_predictor.pkl"
        joblib.dump(self.lgbm_model, lgbm_path)

        # Scaler + metadata
        meta_path = self.save_dir / "price_predictor_meta.pkl"
        joblib.dump(
            {
                "scaler": self.scaler,
                "feature_cols": self.feature_cols,
                "config": self.config,
                "weights": self.weights,
            },
            meta_path,
        )
        logger.info("PriceDirectionPredictor saved successfully.")

    def load(self) -> None:
        """Load all model artefacts from save_dir."""
        logger.info(f"Loading PriceDirectionPredictor from {self.save_dir}")

        meta_path = self.save_dir / "price_predictor_meta.pkl"
        if not meta_path.exists():
            raise FileNotFoundError(f"Model metadata not found: {meta_path}")

        meta = joblib.load(meta_path)
        self.scaler = meta["scaler"]
        self.feature_cols = meta["feature_cols"]
        self.weights = meta["weights"]
        self.n_features = len(self.feature_cols)

        # Restore LSTM
        lstm_path = self.save_dir / "lstm_model.pt"
        ckpt = torch.load(lstm_path, map_location=self.device)
        self.lstm_model = LSTMModel(
            input_size=ckpt["input_size"],
            hidden_size=ckpt["hidden_size"],
            num_layers=ckpt["num_layers"],
            output_size=ckpt["output_size"],
            dropout=ckpt["dropout"],
        ).to(self.device)
        self.lstm_model.load_state_dict(ckpt["state_dict"])
        self.lstm_model.eval()

        # Restore XGBoost
        xgb_path = self.save_dir / "xgb_price_predictor.json"
        self.xgb_model = xgb.XGBClassifier()
        self.xgb_model.load_model(str(xgb_path))

        # Restore LightGBM — full sklearn wrapper persisted with joblib
        lgbm_path = self.save_dir / "lgbm_price_predictor.pkl"
        if not lgbm_path.exists():
            # Backwards-compatibility: try old .txt format if pkl is missing
            lgbm_txt = self.save_dir / "lgbm_price_predictor.txt"
            if lgbm_txt.exists():
                self.lgbm_model = lgb.LGBMClassifier()
                booster = lgb.Booster(model_file=str(lgbm_txt))
                # Attach booster via internal attribute (LightGBM ≤ 3.x)
                self.lgbm_model._Booster = booster
            else:
                raise FileNotFoundError(
                    f"LightGBM model not found at {lgbm_path} or {lgbm_txt}"
                )
        else:
            self.lgbm_model = joblib.load(lgbm_path)

        logger.info("PriceDirectionPredictor loaded successfully.")
