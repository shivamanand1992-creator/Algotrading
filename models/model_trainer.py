"""
model_trainer.py
================
Full training pipeline for the Nifty50 intraday options trading system.

Orchestrates:
  1. Fetching historical data from Angel One
  2. Computing the full technical feature matrix
  3. Training the MarketRegimeClassifier (XGBoost)
  4. Training the PriceDirectionPredictor (LSTM + XGBoost + LightGBM ensemble)
  5. Logging evaluation metrics (accuracy, confusion matrix)
  6. Persisting all artefacts to trained_models/
  7. Staleness checking + automatic retraining
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz
from loguru import logger
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)

# Internal imports
from data.angel_client import AngelOneClient
from features.technical_indicators import TechnicalFeatureEngine
from models.price_predictor import PriceDirectionPredictor
from models.regime_classifier import MarketRegimeClassifier, REGIME_FEATURE_COLS

IST = pytz.timezone("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Nifty50 spot instrument token on NSE (Angel One)
# ---------------------------------------------------------------------------
_NIFTY_TOKEN = "26000"
_NIFTY_SYMBOL = "Nifty 50"
_NIFTY_EXCHANGE = "NSE"
_CANDLE_INTERVAL = "FIVE_MINUTE"

# ---------------------------------------------------------------------------
# Feature columns used for price direction prediction
# (superset; columns actually present in the built matrix are used)
# ---------------------------------------------------------------------------
_PRICE_FEATURE_CANDIDATES: List[str] = [
    # EMA
    "ema_9", "ema_21", "ema_50",
    # RSI / Momentum
    "rsi", "stoch_k", "stoch_d",
    # MACD
    "macd_line", "macd_signal", "macd_hist",
    # Bollinger
    "bb_upper", "bb_middle", "bb_lower", "bb_pct_b", "bb_width",
    # ATR / Volatility
    "atr", "atr_pct", "volatility_10", "volatility_20",
    # VWAP
    "vwap",
    # SuperTrend
    "supertrend", "supertrend_dir",
    # ADX
    "adx", "plus_di", "minus_di",
    # OBV
    "obv",
    # Pivot points
    "pp", "r1", "r2", "s1", "s2",
    # Candlestick patterns
    "pattern_doji", "pattern_hammer", "pattern_shooting_star",
    "pattern_bull_engulfing", "pattern_bear_engulfing",
    # Price action
    "return_1", "return_5", "log_return_1",
    "candle_range", "body_size", "body_to_range",
    "upper_wick", "lower_wick",
    # Support / Resistance
    "dist_to_support", "dist_to_resistance",
    # India VIX features
    "vix_close", "vix_change_5", "vix_is_high", "vix_is_low",
    # Time-of-day features (model learns session patterns)
    "hour", "minute", "minutes_since_open", "minutes_to_close",
    "is_first_30min", "is_last_30min", "day_of_week", "is_expiry_day",
    # Daily multi-timeframe context — big-picture trend
    "daily_ema_20", "daily_ema_50", "daily_ema_200",
    "daily_rsi", "daily_above_200ema", "daily_trend", "daily_weekly_ret",
]


class ModelTrainer:
    """
    Orchestrates data fetching, feature engineering, and model training.

    Parameters
    ----------
    client : AngelOneClient
        An already-connected Angel One API client.
    config : dict
        Full application config dict (from config/config.yaml).
    """

    def __init__(self, client: AngelOneClient, config: dict) -> None:
        self.client = client
        self.config = config

        ml_cfg = config.get("ml", {})
        training_cfg = ml_cfg.get("training", {})

        self.train_days: int = int(training_cfg.get("train_days", 252))
        self.save_dir = Path(
            training_cfg.get("model_save_path", "trained_models")
        )
        self.save_dir.mkdir(parents=True, exist_ok=True)

        # Sub-engines
        self.feature_engine = TechnicalFeatureEngine()
        self.regime_classifier = MarketRegimeClassifier(config)
        self.price_predictor = PriceDirectionPredictor(
            config.get("ml", {}).get("price_predictor", {})
        )

        # Will be set after fetch_training_data
        self._raw_df: Optional[pd.DataFrame] = None
        self._feature_df: Optional[pd.DataFrame] = None
        self._feature_cols: Optional[List[str]] = None

        logger.info(
            f"ModelTrainer initialised. "
            f"train_days={self.train_days}, save_dir={self.save_dir}"
        )

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def fetch_training_data(self, days: int = 252) -> pd.DataFrame:
        """
        Fetch historical Nifty50 5-minute OHLCV data from Angel One.

        Fetches `days` calendar days worth of 5-min candles.  Angel One
        limits each API call to 30-day windows, so multiple calls are
        batched automatically.

        Parameters
        ----------
        days : int
            Number of calendar days of history to fetch (default 252 ≈ 1 trading year).

        Returns
        -------
        pd.DataFrame  — sorted OHLCV with DatetimeIndex (IST-aware)
        """
        logger.info(f"Fetching {days} days of Nifty50 5-min data from Angel One…")

        end_dt = datetime.now(IST)
        start_dt = end_dt - timedelta(days=days)

        all_frames: List[pd.DataFrame] = []

        # Angel One historical data API maximum window per request ~30 days
        window_days = 30
        cursor = start_dt

        while cursor < end_dt:
            chunk_end = min(cursor + timedelta(days=window_days), end_dt)
            from_str = cursor.strftime("%Y-%m-%d %H:%M")
            to_str = chunk_end.strftime("%Y-%m-%d %H:%M")

            try:
                chunk = self.client.get_historical_data(
                    exchange=_NIFTY_EXCHANGE,
                    symbol_token=_NIFTY_TOKEN,
                    interval=_CANDLE_INTERVAL,
                    from_date=from_str,
                    to_date=to_str,
                )
                if chunk is not None and not chunk.empty:
                    all_frames.append(chunk)
                    logger.debug(
                        f"Fetched [{from_str} → {to_str}]: {len(chunk)} candles"
                    )
            except Exception as exc:
                logger.warning(
                    f"Failed to fetch [{from_str} → {to_str}]: {exc}. Skipping chunk."
                )

            cursor = chunk_end
            # Polite delay to respect rate limits
            time.sleep(0.25)

        if not all_frames:
            logger.warning(
                "Angel One returned no candle data for NSE/26000. "
                "Falling back to Yahoo Finance (^NSEI)…"
            )
            return self._fetch_from_yfinance(days)

        df = pd.concat(all_frames, ignore_index=True)
        df = df.drop_duplicates(subset=["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Set DatetimeIndex (IST-aware)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        if df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize(IST)
        else:
            df["timestamp"] = df["timestamp"].dt.tz_convert(IST)
        df = df.set_index("timestamp")

        # Keep only market hours (09:15 – 15:30)
        df = df.between_time("09:15", "15:30")

        logger.info(
            f"Training data fetched: {len(df)} candles "
            f"({df.index[0]} → {df.index[-1]})"
        )
        self._raw_df = df
        return df

    def _fetch_from_yfinance(self, days: int) -> pd.DataFrame:
        """Fallback: fetch NIFTY 50 OHLCV via Yahoo Finance when Angel One returns nothing."""
        import yfinance as yf  # optional dep — installed alongside Angel One client

        # yfinance 5-min data is only available for the last 60 calendar days
        actual_days = min(days, 60)
        logger.info(
            f"Yahoo Finance fallback: fetching {actual_days} days of 5-min ^NSEI data…"
        )

        ticker = yf.Ticker("^NSEI")
        df = ticker.history(period=f"{actual_days}d", interval="5m")

        if df is None or df.empty:
            raise RuntimeError(
                "fetch_training_data: No data from Angel One or Yahoo Finance (^NSEI)."
            )

        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        df.index.name = "timestamp"

        # Localise to IST
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")

        df = df[["open", "high", "low", "close", "volume"]]
        df = df.between_time("09:15", "15:30")
        df = df[~df.index.duplicated(keep="first")]
        df = df.sort_index()

        # ^NSEI is an index — Yahoo Finance reports 0 volume for every bar.
        # Replace with synthetic relative volume so VWAP is computable and
        # the final dropna(how="any") in build_feature_matrix doesn't wipe
        # all rows because the vwap column is all-NaN.
        if "volume" in df.columns and (df["volume"] == 0).all():
            df["volume"] = (df["close"] / df["close"].max() * 100_000).round().astype(int).clip(lower=1)
            logger.debug("Synthetic volume applied for ^NSEI index data.")

        # ------------------------------------------------------------------
        # Time-of-day features — model learns intraday session patterns
        # ------------------------------------------------------------------
        df["hour"]               = df.index.hour
        df["minute"]             = df.index.minute
        df["minutes_since_open"] = (df.index.hour - 9) * 60 + df.index.minute - 15
        df["minutes_to_close"]   = (15 * 60 + 30) - (df.index.hour * 60 + df.index.minute)
        df["is_first_30min"]     = (df["minutes_since_open"] <= 30).astype(int)
        df["is_last_30min"]      = (df["minutes_to_close"]   <= 30).astype(int)
        df["day_of_week"]        = df.index.dayofweek   # 0=Mon … 4=Fri
        df["is_expiry_day"]      = (df.index.dayofweek == 3).astype(int)  # Thursday

        # ------------------------------------------------------------------
        # India VIX features — strong predictor of options premium & regime
        # ------------------------------------------------------------------
        try:
            vix_df = yf.Ticker("^INDIAVIX").history(
                period=f"{actual_days}d", interval="5m"
            )
            if vix_df is not None and not vix_df.empty:
                if vix_df.index.tz is None:
                    vix_df.index = vix_df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
                else:
                    vix_df.index = vix_df.index.tz_convert("Asia/Kolkata")
                vix_df = vix_df[["Close"]].rename(columns={"Close": "vix_close"})
                # Align to Nifty 5-min bars (VIX may have slightly different timestamps)
                df = df.merge(vix_df, left_index=True, right_index=True, how="left")
                df["vix_close"]    = df["vix_close"].ffill().bfill()
                df["vix_change_5"] = df["vix_close"].pct_change(5)   # 5-bar % change
                df["vix_is_high"]  = (df["vix_close"] > 20).astype(int)
                df["vix_is_low"]   = (df["vix_close"] < 12).astype(int)
                logger.info(f"India VIX merged: {df['vix_close'].notna().sum()} rows enriched.")
        except Exception as _vix_err:
            logger.warning(f"VIX fetch skipped ({_vix_err}) — training without VIX features.")

        # ------------------------------------------------------------------
        # Multi-timeframe daily context — big-picture trend features
        # ------------------------------------------------------------------
        try:
            daily_ctx = self._fetch_daily_context(years=2)
            if daily_ctx is not None and not daily_ctx.empty:
                # Normalise daily index to tz-naive midnight Timestamps
                daily_ctx.index = pd.to_datetime(daily_ctx.index).normalize()
                if getattr(daily_ctx.index, "tz", None) is not None:
                    daily_ctx.index = daily_ctx.index.tz_localize(None)

                # Extract date component of each 5-min bar as tz-naive Timestamp
                bar_dates = pd.to_datetime(df.index.date)

                _daily_cols = [
                    "daily_ema_20", "daily_ema_50", "daily_ema_200",
                    "daily_rsi", "daily_above_200ema", "daily_trend", "daily_weekly_ret",
                ]
                for col in _daily_cols:
                    if col in daily_ctx.columns:
                        val_dict = daily_ctx[col].to_dict()
                        df[col] = [val_dict.get(d, np.nan) for d in bar_dates]

                # Fill forward/back so mid-session bars get the same daily value
                present = [c for c in _daily_cols if c in df.columns]
                if present:
                    df[present] = df[present].ffill().bfill()

                logger.info(
                    f"Daily context merged: {daily_ctx.shape[0]} trading days enriched "
                    f"({daily_ctx.index[0].date()} → {daily_ctx.index[-1].date()})."
                )
        except Exception as _daily_err:
            logger.warning(f"Daily context skipped ({_daily_err}) — continuing without daily features.")

        logger.info(
            f"Yahoo Finance data fetched: {len(df)} candles "
            f"({df.index[0]} → {df.index[-1]})"
        )
        self._raw_df = df
        return df

    def _fetch_daily_context(self, years: int = 2) -> Optional[pd.DataFrame]:
        """Fetch daily OHLCV + compute slow trend indicators for multi-timeframe context.

        Tries NSE India's public API first; falls back to Yahoo Finance (^NSEI, 2yr daily).
        Returns DataFrame indexed by tz-naive midnight Timestamps with columns:
        daily_ema_20/50/200, daily_rsi, daily_above_200ema, daily_trend, daily_weekly_ret.
        """
        import yfinance as yf

        df: Optional[pd.DataFrame] = None

        # Try NSE first (2+ years of history available)
        try:
            df = self._fetch_nse_daily_api(years=years)
        except Exception as e:
            logger.debug(f"NSE daily API unavailable ({e}), falling back to Yahoo Finance…")

        # Yahoo Finance fallback
        if df is None or df.empty:
            try:
                raw = yf.Ticker("^NSEI").history(period=f"{years * 365}d", interval="1d")
                if raw is not None and not raw.empty:
                    raw = raw.rename(columns={"Open": "open", "High": "high",
                                              "Low": "low", "Close": "close"})
                    raw.index.name = "date"
                    if getattr(raw.index, "tz", None) is not None:
                        raw.index = raw.index.tz_localize(None)
                    raw.index = pd.to_datetime(raw.index).normalize()
                    df = raw[["open", "high", "low", "close"]].copy()
                    logger.info(f"Daily context via Yahoo Finance: {len(df)} trading days")
            except Exception as e2:
                logger.warning(f"Yahoo Finance daily context failed: {e2}")

        if df is None or df.empty:
            return None

        # ── Compute slow indicators ──────────────────────────────────────
        c = df["close"]

        df["daily_ema_20"]  = c.ewm(span=20,  adjust=False).mean()
        df["daily_ema_50"]  = c.ewm(span=50,  adjust=False).mean()
        df["daily_ema_200"] = c.ewm(span=200, adjust=False).mean()

        delta = c.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        df["daily_rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

        df["daily_above_200ema"] = (c > df["daily_ema_200"]).astype(int)

        ema_diff_pct = (df["daily_ema_20"] - df["daily_ema_50"]) / df["daily_ema_50"]
        df["daily_trend"] = np.where(ema_diff_pct > 0.003,  1,
                            np.where(ema_diff_pct < -0.003, -1, 0)).astype(int)

        df["daily_weekly_ret"] = c.pct_change(5)

        keep = [
            "daily_ema_20", "daily_ema_50", "daily_ema_200",
            "daily_rsi", "daily_above_200ema", "daily_trend", "daily_weekly_ret",
        ]
        df = df[[col for col in keep if col in df.columns]].ffill().bfill()
        return df

    def _fetch_nse_daily_api(self, years: int = 2) -> Optional[pd.DataFrame]:
        """Fetch Nifty 50 daily OHLCV from NSE India's public API.

        NSE requires a browser-style session cookie obtained by visiting the homepage first.
        Returns DataFrame indexed by tz-naive date Timestamps with open/high/low/close columns.
        """
        import requests
        from datetime import date as _date

        end_d   = _date.today()
        start_d = end_d - timedelta(days=years * 365 + 10)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.nseindia.com/",
        }
        session = requests.Session()
        session.headers.update(headers)

        # Cookie warm-up — two quick GETs to establish an NSE session
        session.get("https://www.nseindia.com", timeout=10)
        time.sleep(0.5)
        session.get(
            "https://www.nseindia.com/market-data/live-equity-market",
            timeout=10,
        )
        time.sleep(0.5)

        url = (
            "https://www.nseindia.com/api/historical/indicesHistory"
            f"?name=NIFTY%2050"
            f"&startDate={start_d.strftime('%d-%m-%Y')}"
            f"&endDate={end_d.strftime('%d-%m-%Y')}"
        )
        resp = session.get(url, timeout=20)
        resp.raise_for_status()

        records = (resp.json().get("data") or {}).get("indexCloseOnlineRecords", [])
        if not records:
            raise ValueError("NSE API returned empty indexCloseOnlineRecords")

        rows = []
        for r in records:
            try:
                dt = datetime.strptime(r["EOD_TIMESTAMP"], "%d-%b-%Y")
                rows.append({
                    "date":  dt,
                    "open":  float(r.get("EOD_OPEN_INDEX_VAL",  0) or 0),
                    "high":  float(r.get("EOD_HIGH_INDEX_VAL",  0) or 0),
                    "low":   float(r.get("EOD_LOW_INDEX_VAL",   0) or 0),
                    "close": float(r.get("EOD_CLOSE_INDEX_VAL", 0) or 0),
                })
            except Exception:
                continue

        if not rows:
            raise ValueError("NSE API: no parseable records in response")

        df = pd.DataFrame(rows).set_index("date").sort_index()
        df.index = pd.to_datetime(df.index).normalize()
        logger.info(
            f"NSE daily data: {len(df)} trading days "
            f"({df.index[0].date()} → {df.index[-1].date()})"
        )
        return df

    # ------------------------------------------------------------------
    # Feature engineering
    # ------------------------------------------------------------------

    def build_feature_matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Run TechnicalFeatureEngine on raw OHLCV and return a clean feature DataFrame.

        Steps
        -----
        1. Compute all technical indicators via TechnicalFeatureEngine.compute_all()
        2. (Optionally) add any options-derived features if available.
        3. Drop rows with all-NaN feature values (warm-up period).
        4. Forward-fill remaining NaN values (indicator warm-up artefacts).
        5. Clip extreme outliers (±10 std from rolling mean) per feature.

        Parameters
        ----------
        df : pd.DataFrame
            Raw OHLCV DataFrame (columns: open, high, low, close, volume).

        Returns
        -------
        pd.DataFrame  — enriched DataFrame with all feature columns.
        """
        logger.info("Building feature matrix…")

        # 1. Technical indicators
        feat_df = self.feature_engine.compute_all(df)

        # 2. Drop leading rows where all indicator columns are NaN
        indicator_cols = [c for c in feat_df.columns
                          if c not in ("open", "high", "low", "close", "volume")]
        feat_df = feat_df.dropna(subset=indicator_cols, how="all")

        # 3. Forward-fill then back-fill residual NaN values from warm-up
        # bfill ensures the very first bars (before indicators warm up) are filled
        # so the final dropna doesn't eliminate the entire dataset.
        feat_df = feat_df.ffill().bfill()

        # 4. Clip extreme outliers (±10σ window-based)
        for col in indicator_cols:
            if feat_df[col].dtype in (np.float32, np.float64, float):
                mu = feat_df[col].rolling(window=200, min_periods=10).mean()
                sigma = feat_df[col].rolling(window=200, min_periods=10).std()
                lower = mu - 10 * sigma
                upper = mu + 10 * sigma
                feat_df[col] = feat_df[col].clip(lower=lower, upper=upper)

        # 5. Final NaN drop (safety)
        feat_df = feat_df.dropna(how="any", subset=[
            c for c in feat_df.columns
            if c not in ("open", "high", "low", "close", "volume")
        ])

        logger.info(
            f"Feature matrix built: {feat_df.shape[0]} rows × "
            f"{feat_df.shape[1]} columns."
        )
        self._feature_df = feat_df
        return feat_df

    # ------------------------------------------------------------------
    # Full training pipeline
    # ------------------------------------------------------------------

    def train_all_models(self, on_step=None) -> None:
        """
        End-to-end training pipeline.

        Steps
        -----
        1. Fetch historical Nifty50 spot data (5-min candles).
        2. Build the full feature matrix.
        3. Train MarketRegimeClassifier.
        4. Train PriceDirectionPredictor.
        5. Log evaluation metrics.
        6. Save all models to trained_models/.

        Parameters
        ----------
        on_step : callable, optional
            Called with a progress string at the start of each step.
        """
        def _step(msg: str):
            logger.info(msg)
            if on_step:
                on_step(msg)

        _step("========== ModelTrainer: train_all_models() ==========")

        # 1. Fetch data
        _step("Step 1/5: Fetching training data…")
        df_raw = self.fetch_training_data(days=self.train_days)

        # 2. Build features
        _step("Step 2/5: Building feature matrix…")
        df_feat = self.build_feature_matrix(df_raw)

        # 3. Train regime classifier
        _step("Step 3/5: Training MarketRegimeClassifier…")
        self.regime_classifier.train(df_feat)

        # 4. Determine price-predictor feature columns
        _step("Step 4/5: Training PriceDirectionPredictor…")
        feature_cols = self.get_feature_columns(df_feat)
        self._feature_cols = feature_cols
        self.price_predictor.train(df_feat, feature_cols)

        # 5. Cross-model evaluation summary
        _step("Step 5/5: Evaluating on holdout set…")
        split_idx = int(len(df_feat) * 0.8)
        test_df = df_feat.iloc[split_idx:]
        if len(test_df) > 0:
            self.evaluate_models(test_df)
        else:
            logger.warning("No holdout rows available for evaluation.")

        _step("All models trained and saved successfully.")

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_models(self, test_df: pd.DataFrame) -> Dict[str, object]:
        """
        Evaluate both models on a holdout set and print reports.

        Parameters
        ----------
        test_df : pd.DataFrame
            Feature-enriched test DataFrame (same columns as training).

        Returns
        -------
        dict with keys 'regime_accuracy', 'price_accuracy'
        """
        results: Dict[str, object] = {}

        # ── Regime classifier ──────────────────────────────────────────
        logger.info("--- Evaluating MarketRegimeClassifier ---")
        try:
            feat_cols_regime = [
                c for c in self.regime_classifier.feature_cols
                if c in test_df.columns
            ]
            if feat_cols_regime and self.regime_classifier.model is not None:
                X_test_regime = self.regime_classifier.scaler.transform(
                    test_df[feat_cols_regime]
                    .reindex(columns=self.regime_classifier.feature_cols, fill_value=0)
                    .values.astype(np.float32)
                )
                # Auto-label test set for evaluation
                from models.regime_classifier import _create_regime_labels
                y_true_str = _create_regime_labels(test_df).values
                y_true_enc = self.regime_classifier.label_encoder.transform(y_true_str)
                y_pred_enc = self.regime_classifier.model.predict(X_test_regime)

                acc = accuracy_score(y_true_enc, y_pred_enc)
                results["regime_accuracy"] = acc
                logger.info(f"Regime classifier test accuracy: {acc:.4f}")

                target_names = list(
                    self.regime_classifier.label_encoder.classes_
                )
                report = classification_report(
                    y_true_enc, y_pred_enc,
                    target_names=target_names,
                    zero_division=0,
                )
                logger.info(f"Regime classification report:\n{report}")

                cm = confusion_matrix(y_true_enc, y_pred_enc)
                logger.info(
                    f"Regime confusion matrix ({target_names}):\n{cm}"
                )
        except Exception as exc:
            logger.warning(f"Regime evaluation failed: {exc}")

        # ── Price direction predictor ──────────────────────────────────
        logger.info("--- Evaluating PriceDirectionPredictor ---")
        try:
            if (self.price_predictor.lstm_model is not None
                    and self._feature_cols is not None):
                feature_cols = [
                    c for c in self._feature_cols if c in test_df.columns
                ]
                # Need to create targets for evaluation
                df_eval = test_df.copy()
                df_eval["target"] = self.price_predictor.create_target(df_eval)
                df_eval = df_eval.dropna(
                    subset=["target"] + feature_cols
                )

                if len(df_eval) > self.price_predictor.lookback + 5:
                    df_scaled = df_eval.copy()
                    df_scaled[feature_cols] = (
                        self.price_predictor.scaler.transform(df_scaled[feature_cols])
                    )
                    X_lstm, X_tab, y = self.price_predictor.prepare_sequences(
                        df_scaled, feature_cols, "target",
                        self.price_predictor.lookback,
                    )
                    self.price_predictor._evaluate_ensemble(X_lstm, X_tab, y)
                    # Simple accuracy
                    acc = accuracy_score(
                        y,
                        np.argmax(
                            self.price_predictor._ensemble_predict(
                                *_batch_lstm_predict(
                                    self.price_predictor, X_lstm
                                ),
                                self.price_predictor.xgb_model.predict_proba(X_tab),
                                self.price_predictor.lgbm_model.predict_proba(X_tab),
                                self.price_predictor.weights,
                            ),
                            axis=1,
                        ),
                    )
                    results["price_accuracy"] = acc
                    logger.info(f"Price predictor test accuracy: {acc:.4f}")
        except Exception as exc:
            logger.warning(f"Price predictor evaluation failed: {exc}")

        return results

    # ------------------------------------------------------------------
    # Staleness check & automatic retraining
    # ------------------------------------------------------------------

    def retrain_if_needed(self, max_age_days: int = 7) -> bool:
        """
        Retrain all models if the persisted artefacts are older than
        `max_age_days` days.

        Parameters
        ----------
        max_age_days : int
            Maximum age (in days) of model artefacts before retraining.
            Default is 7 (weekly retraining schedule).

        Returns
        -------
        bool — True if retraining was triggered, False otherwise.
        """
        # Use the regime classifier metadata file as the staleness sentinel
        sentinel = self.save_dir / "regime_classifier_meta.pkl"

        if not sentinel.exists():
            logger.info(
                "No saved model artefacts found. Starting initial training."
            )
            self.train_all_models()
            return True

        age = datetime.now() - datetime.fromtimestamp(sentinel.stat().st_mtime)
        age_days = age.total_seconds() / 86_400

        if age_days > max_age_days:
            logger.info(
                f"Models are {age_days:.1f} days old (limit={max_age_days}). "
                "Retraining now…"
            )
            self.train_all_models()
            return True

        logger.info(
            f"Models are {age_days:.1f} days old — within the {max_age_days}-day "
            "threshold. No retraining needed."
        )
        return False

    # ------------------------------------------------------------------
    # Feature column registry
    # ------------------------------------------------------------------

    def get_feature_columns(
        self, df: Optional[pd.DataFrame] = None
    ) -> List[str]:
        """
        Return the ordered list of feature column names used for training
        the PriceDirectionPredictor.

        If a DataFrame is supplied the list is filtered to only columns
        that are actually present in that DataFrame.  If no DataFrame is
        given the cached list is returned (populated after training).

        Parameters
        ----------
        df : pd.DataFrame, optional
            Feature-enriched DataFrame to intersect against.

        Returns
        -------
        List[str]
        """
        if df is not None:
            available = [c for c in _PRICE_FEATURE_CANDIDATES if c in df.columns]
            # Exclude raw OHLCV and volume — only derived features
            available = [
                c for c in available
                if c not in ("open", "high", "low", "close", "volume")
            ]
            if not available:
                raise ValueError(
                    "get_feature_columns: no candidate feature columns found in "
                    "the supplied DataFrame.  Run build_feature_matrix() first."
                )
            logger.debug(f"Feature columns selected: {len(available)}")
            return available

        if self._feature_cols is not None:
            return self._feature_cols

        # Fall back to full candidate list (caller's responsibility to filter)
        return list(_PRICE_FEATURE_CANDIDATES)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _batch_lstm_predict(
    predictor: PriceDirectionPredictor,
    X_lstm: np.ndarray,
    batch_size: int = 64,
) -> np.ndarray:
    """
    Run batched LSTM inference and return probability array (n, 3).
    Avoids loading the full dataset into GPU memory at once.
    """
    import torch

    predictor.lstm_model.eval()
    probs_list = []
    with torch.no_grad():
        for start in range(0, len(X_lstm), batch_size):
            end = start + batch_size
            batch = torch.tensor(
                X_lstm[start:end], dtype=torch.float32
            ).to(predictor.device)
            logits = predictor.lstm_model(batch)
            p = torch.softmax(logits, dim=-1).cpu().numpy()
            probs_list.append(p)
    return np.vstack(probs_list)
