"""
Real-Time ML Scoring Service - Hybrid ML + Technical Analysis

Every 5 minutes during market hours:
1. Fetch latest candles for the universe
2. Generate ML prediction (trained XGBoost model)
3. Generate Technical confirmation (RSI, MACD, Bollinger Bands, Volume)
4. Combine scores (only signal if BOTH ML ≥ 60 AND Technical ≥ 60)
5. Final signal = (ML × 0.6) + (Technical × 0.4)
6. Paper-trade signals and track P&L

Hybrid approach: ML for pattern recognition, Technical for entry timing confirmation
"""

import json
import sqlite3
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
from loguru import logger

from backend.ml.data_importer import DB_PATH, UNIVERSE, get_db
from backend.ml.feature_engine import compute_features, FEATURE_COLS
from backend.ml.train_model import MODEL_PATH, META_PATH
from backend.ml.label_generator import TARGET_PCT, SL_PCT, HOLD_MINUTES

_IST = timezone(timedelta(hours=5, minutes=30))

# Score only the most liquid subset live (reduced to prevent Angel One rate limiting)
# Angel One allows ~1 req/sec; 12 symbols @ 1.2s/symbol = ~14.4s per cycle
LIVE_UNIVERSE = UNIVERSE[:12]


class MLScoringService:
    """Singleton service for live ML scoring + paper trading."""

    _instance = None

    @classmethod
    def get_instance(cls) -> "MLScoringService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.model = None
        self.meta: Dict = {}
        self.threshold = 0.70
        self.last_update: Optional[str] = None
        self.latest_scores: List[Dict] = []
        self.active_signals: List[Dict] = []
        self.paper_positions: List[Dict] = []
        self.paper_trades_closed: List[Dict] = []
        self.paper_pnl_pct = 0.0
        self.enabled = False
        self.mode = "paper"  # paper only until backtest proves expectancy

        # Progress tracking for import/training
        self.import_progress = {
            "status": "idle",  # idle, importing, complete, failed
            "message": "",
            "progress_pct": 0,
            "stocks_done": 0,
            "total_stocks": 0,
        }
        self.training_progress = {
            "status": "idle",  # idle, training, complete, failed
            "message": "",
            "progress_pct": 0,
        }

        self._load_model()

    # ------------------------------------------------------------------ model

    def _load_model(self):
        try:
            import xgboost as xgb
            if MODEL_PATH.exists() and META_PATH.exists():
                self.model = xgb.XGBClassifier()
                self.model.load_model(str(MODEL_PATH))
                self.meta = json.loads(META_PATH.read_text())
                self.threshold = self.meta.get("threshold", 0.70)
                logger.info(
                    f"[MLScore] Model loaded ({self.meta.get('model_version')}), "
                    f"threshold={self.threshold}, tradeable={self.meta.get('tradeable')}"
                )
            else:
                logger.warning("[MLScore] No trained model found — run train_model first")
        except Exception as e:
            logger.error(f"[MLScore] Model load failed: {e}")

    def reload_model(self):
        self._load_model()

    # ------------------------------------------------------------------ cycle

    async def run_cycle(self) -> Dict:
        """One scoring cycle. Called every 5 min by the scheduler."""
        now = datetime.now(_IST)
        if not self._is_market_hours(now):
            # Manage EOD: close all paper positions at 15:15
            if self.paper_positions and now.time() >= datetime.strptime("15:15", "%H:%M").time():
                await self._close_all_paper("eod")
            return {"status": "market_closed"}

        try:
            # Use hybrid ML + Technical scoring (ML 60%, Technical 40%)
            # Only generates signals when BOTH ML and Technical confirm (both >= 60)
            scores, signals = await asyncio.to_thread(self._hybrid_scoring)

            self.latest_scores = scores
            self.last_update = now.strftime("%H:%M:%S")

            # Manage existing paper positions first (SL/target checks)
            await self._manage_paper_positions()

            # Open new paper positions from fresh signals (max 2 concurrent)
            for sig in signals:
                if len(self.paper_positions) >= 2:
                    break
                if any(p["symbol"] == sig["symbol"] for p in self.paper_positions):
                    continue
                self._open_paper_position(sig)

            self.active_signals = signals
            logger.info(
                f"[MLScore] Cycle done: {len(scores)} scored, {len(signals)} signals, "
                f"{len(self.paper_positions)} paper positions"
            )
            return {"status": "ok", "scored": len(scores), "signals": len(signals)}

        except Exception as e:
            logger.error(f"[MLScore] Cycle failed: {e}")
            return {"status": "error", "error": str(e)}

    def _calculate_technical_score(self, df: pd.DataFrame) -> Tuple[float, Dict[str, int]]:
        """
        Calculate technical confirmation score (0-100) and individual component scores.
        Returns: (avg_technical_score, components_dict)
        Components: trend, momentum, volume, pattern (all 0-100)
        """
        if df is None or len(df) < 20:
            return 50.0, {"trend": 50, "momentum": 50, "volume": 50, "pattern": 50}

        close = df["close"].values
        volume = df["volume"].values
        scores = []
        components = {}

        # RSI (14-period) - used for MOMENTUM
        rsi_score = 50.0
        if len(close) >= 14:
            delta = np.diff(close)
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            avg_gain = np.mean(gain[-14:])
            avg_loss = np.mean(loss[-14:])
            rs = avg_gain / avg_loss if avg_loss != 0 else 1
            rsi = 100 - (100 / (1 + rs))
            rsi_score = 50 + (rsi - 50) * 0.6
            scores.append(rsi_score)

        # MACD (12, 26, 9) - also for MOMENTUM
        macd_score = 50.0
        if len(close) >= 26:
            ema12 = pd.Series(close).ewm(span=12).mean().values
            ema26 = pd.Series(close).ewm(span=26).mean().values
            macd_line = ema12 - ema26
            signal_line = pd.Series(macd_line).ewm(span=9).mean().values
            histogram = macd_line - signal_line
            if histogram[-1] > 0:
                macd_score = 55 + min(20, histogram[-1] * 100)
            else:
                macd_score = 45 - min(20, -histogram[-1] * 100)
            macd_score = np.clip(macd_score, 0, 100)
            scores.append(macd_score)

        # Bollinger Bands (20-period) - used for PATTERN
        pattern_score = 50.0
        if len(close) >= 20:
            sma20 = np.mean(close[-20:])
            std20 = np.std(close[-20:])
            bb_upper = sma20 + (std20 * 2)
            bb_lower = sma20 - (std20 * 2)
            current = close[-1]
            if std20 > 0:
                bb_position = (current - bb_lower) / (bb_upper - bb_lower)
                pattern_score = bb_position * 100
            else:
                pattern_score = 50.0
            pattern_score = np.clip(pattern_score, 0, 100)
            scores.append(pattern_score)

        # Volume surge - VOLUME component
        volume_score = 50.0
        if len(volume) >= 5:
            avg_vol = np.mean(volume[-20:])
            current_vol = volume[-1]
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1
            volume_score = 50 + min(30, (vol_ratio - 1) * 30)
            volume_score = np.clip(volume_score, 0, 100)
            scores.append(volume_score)

        # Trend (close above/below SMA50) - TREND component
        trend_score = 50.0
        if len(close) >= 50:
            sma50 = np.mean(close[-50:])
            trend_score = 60 if close[-1] > sma50 else 40
            scores.append(trend_score)

        # Momentum = average of RSI and MACD
        momentum_score = (rsi_score + macd_score) / 2

        # Build components dict for UI
        components = {
            "trend": int(trend_score),
            "momentum": int(momentum_score),
            "volume": int(volume_score),
            "pattern": int(pattern_score),
        }

        # Return weighted average of all technical scores
        avg_technical = np.mean(scores) if scores else 50.0
        return avg_technical, components

    def _ml_score(self) -> Dict:
        """Get ML predictions for LIVE_UNIVERSE (12 liquid stocks) using trained model."""
        if self.model is None:
            logger.warning("[MLScore] Model not loaded, skipping ML scoring")
            return {}

        import time as time_module
        from backend.dependencies import get_angel_client

        ml_scores = {}
        conn = sqlite3.connect(DB_PATH)
        cutoff = (datetime.now(_IST) - timedelta(days=5)).strftime("%Y-%m-%d")
        angel_client = get_angel_client()

        for symbol in LIVE_UNIVERSE:
            try:
                # Fetch 5-day candles for feature engineering
                df = pd.read_sql(
                    "SELECT * FROM candles_5min WHERE symbol=? AND timestamp>=? ORDER BY timestamp",
                    conn, params=(symbol, cutoff)
                )

                if len(df) < 60:
                    logger.debug(f"[MLScore] {symbol} insufficient candles ({len(df)})")
                    continue

                # Compute features for ML model
                features = compute_features(df)
                if len(features) == 0:
                    continue

                row = features.iloc[[-1]]
                proba = float(self.model.predict_proba(row[FEATURE_COLS])[:, 1][0])
                ml_score = int(proba * 100)

                # Get live price
                ltp = None
                if angel_client:
                    try:
                        token = angel_client.search_scrip("NSE", symbol)
                        if token:
                            quote = angel_client.get_quote("NSE", symbol, token)
                            if quote and quote.get("ltp", 0) > 0:
                                ltp = float(quote["ltp"])
                        time_module.sleep(1.1)
                    except Exception:
                        pass

                if ltp is None:
                    ltp = float(row.iloc[0]["close"])

                ml_scores[symbol] = {
                    "ml_score": ml_score,
                    "price": round(ltp, 2),
                    "candles": len(df),
                }

            except Exception as e:
                logger.debug(f"[MLScore] {symbol} ML score failed: {e}")
                continue

        conn.close()
        return ml_scores

    def _hybrid_scoring(self) -> Tuple[List[Dict], List[Dict]]:
        """Hybrid scoring: ML (60%) + Technical (40%). Only signal if BOTH ≥ 60."""
        scores, signals = [], []
        now = datetime.now(_IST)
        conn = sqlite3.connect(DB_PATH)

        # Get ML predictions for liquid stocks
        ml_predictions = self._ml_score()
        logger.info(f"[MLScore] ML predictions for {len(ml_predictions)} stocks")

        cutoff = (datetime.now(_IST) - timedelta(days=5)).strftime("%Y-%m-%d")

        for symbol in LIVE_UNIVERSE:
            try:
                if symbol not in ml_predictions:
                    continue

                ml_data = ml_predictions[symbol]
                ml_score = ml_data["ml_score"]
                ltp = ml_data["price"]

                # Calculate technical score from 20-day candles
                candle_df = pd.read_sql(
                    "SELECT * FROM candles_5min WHERE symbol=? AND timestamp>=? ORDER BY timestamp DESC LIMIT 400",
                    conn, params=(symbol, (datetime.now(_IST) - timedelta(days=2)).strftime("%Y-%m-%d"))
                )

                tech_score, tech_components = self._calculate_technical_score(candle_df)

                # Hybrid score: ML (60% weight) + Technical (40% weight)
                hybrid_score = int((ml_score * 0.6) + (tech_score * 0.4))

                # Get technical details for breakdown
                rsi = self._get_rsi(candle_df)
                macd_histogram = self._get_macd_histogram(candle_df)

                entry = {
                    "symbol": symbol,
                    "score": hybrid_score,
                    "price": ltp,
                    "probability": float(hybrid_score),
                    "ml_score": ml_score,
                    "technical_score": int(tech_score),
                    "features": {
                        **tech_components,  # Include individual component scores: trend, momentum, volume, pattern
                        "rsi": rsi,
                        "macd": "Bullish" if macd_histogram > 0 else "Bearish",
                        "ml_confirmation": "✓" if ml_score >= 60 else "✗",
                        "technical_confirmation": "✓" if tech_score >= 60 else "✗",
                    },
                    "timestamp": now.isoformat(),
                }
                scores.append(entry)

                # Generate signals only if BOTH ML and Technical confirm (both ≥ 60)
                if ml_score >= 60 and tech_score >= 60:
                    sl = round(ltp * 0.98, 2)
                    target = round(ltp * 1.03, 2)
                    risk = ltp - sl
                    reward = target - ltp
                    rr = round(reward / risk, 2) if risk > 0 else 1.5

                    if rr >= 1.2:
                        signals.append({
                            **entry,
                            "entry": ltp,
                            "stop_loss": sl,
                            "target": target,
                            "reward_risk": rr,
                            "hold_time": 45,
                            "confidence": f"ML:{ml_score}% + Technical:{int(tech_score)}% = {hybrid_score}%",
                        })

            except Exception as e:
                logger.debug(f"[MLScore] {symbol} hybrid score failed: {e}")
                continue

        conn.close()
        scores.sort(key=lambda s: -s["score"])
        num_signals = len(signals)
        logger.info(
            f"[MLScore] Hybrid scoring: {len(scores)} stocks analyzed, "
            f"{num_signals} signals (ML+Technical confirmed)"
        )
        return scores[:20], signals

    def _get_rsi(self, df: pd.DataFrame) -> int:
        """Calculate 14-period RSI."""
        if df is None or len(df) < 14:
            return 50
        close = df["close"].values[-14:]
        delta = np.diff(close)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = np.mean(gain)
        avg_loss = np.mean(loss)
        rs = avg_gain / avg_loss if avg_loss != 0 else 1
        rsi = 100 - (100 / (1 + rs))
        return int(rsi)

    def _get_macd_histogram(self, df: pd.DataFrame) -> float:
        """Calculate MACD histogram."""
        if df is None or len(df) < 26:
            return 0
        close = df["close"].values
        ema12 = pd.Series(close).ewm(span=12).mean().values
        ema26 = pd.Series(close).ewm(span=26).mean().values
        macd_line = ema12 - ema26
        signal_line = pd.Series(macd_line).ewm(span=9).mean().values
        histogram = macd_line - signal_line
        return float(histogram[-1])

    def _score_universe(self):
        """Fetch recent candles from DB + live quote, score every stock."""
        from backend.dependencies import get_angel_client
        client = get_angel_client()

        conn = sqlite3.connect(DB_PATH)
        nifty = pd.read_sql(
            "SELECT * FROM index_candles_5min WHERE symbol='NIFTY50' "
            "ORDER BY timestamp DESC LIMIT 500", conn
        ).iloc[::-1]

        scores, signals = [], []
        cutoff = (datetime.now(_IST) - timedelta(days=5)).strftime("%Y-%m-%d")

        for symbol in LIVE_UNIVERSE:
            try:
                df = pd.read_sql(
                    "SELECT * FROM candles_5min WHERE symbol=? AND timestamp>=? ORDER BY timestamp",
                    conn, params=(symbol, cutoff),
                )
                if len(df) < 60:
                    continue

                feats = compute_features(df, index_df=nifty if len(nifty) else None)
                if len(feats) == 0:
                    continue
                row = feats.iloc[[-1]]

                proba = float(self.model.predict_proba(row[FEATURE_COLS])[:, 1][0])
                sub = self._subscores(row.iloc[0])
                final_score = int(round(proba * 100))
                price = float(row.iloc[0]["close"])

                entry = {
                    "symbol": symbol,
                    "score": final_score,
                    "price": price,
                    "probability": round(proba * 100, 1),
                    "features": sub,
                    "timestamp": datetime.now(_IST).isoformat(),
                }
                scores.append(entry)

                # Signal: model probability above trained threshold
                if proba >= self.threshold:
                    atr = float(row.iloc[0]["atr"])
                    sl = round(price - max(atr, price * SL_PCT / 100), 2)
                    target = round(price + price * TARGET_PCT / 100, 2)
                    risk = price - sl
                    reward = target - price
                    rr = round(reward / risk, 2) if risk > 0 else 0
                    if rr >= 1.2:
                        signals.append({
                            **entry,
                            "entry": price,
                            "stop_loss": sl,
                            "target": target,
                            "reward_risk": rr,
                            "hold_time": HOLD_MINUTES,
                        })
            except Exception as e:
                logger.debug(f"[MLScore] {symbol} scoring failed: {e}")

        conn.close()
        scores.sort(key=lambda s: -s["score"])
        return scores[:15], signals

    @staticmethod
    def _subscores(row) -> Dict[str, int]:
        """Human-readable 0-100 breakdown per feature group (for dashboard)."""
        def clip(v):
            return int(np.clip(v, 0, 100))

        trend = clip(50 + row["price_vs_ema20"] * 15 + row["ema_aligned_bull"] * 20)
        momentum = clip(row["rsi"] + row["macd_hist_norm"] * 30)
        volume = clip(row["rel_volume"] * 40)
        pattern = clip(
            50 + row["is_breakout"] * 30 + row["above_opening_range"] * 15
            - row["is_breakdown"] * 30 + row["is_inside_bar"] * 5
        )
        return {"trend": trend, "momentum": momentum, "volume": volume, "pattern": pattern}

    # ------------------------------------------------------------ paper trades

    def _open_paper_position(self, sig: Dict):
        pos = {
            "symbol": sig["symbol"],
            "entry": sig["entry"],
            "stop_loss": sig["stop_loss"],
            "target": sig["target"],
            "probability": sig["probability"],
            "opened_at": datetime.now(_IST).isoformat(),
            "expires_at": (datetime.now(_IST) + timedelta(minutes=HOLD_MINUTES)).isoformat(),
        }
        self.paper_positions.append(pos)
        logger.info(f"[MLScore] 📄 PAPER BUY {pos['symbol']} @ ₹{pos['entry']} "
                    f"SL={pos['stop_loss']} T={pos['target']} P={pos['probability']}%")

    async def _manage_paper_positions(self):
        """Check SL/target/time exit using latest candle close."""
        if not self.paper_positions:
            return
        conn = sqlite3.connect(DB_PATH)
        now = datetime.now(_IST)
        still_open = []

        for pos in self.paper_positions:
            df = pd.read_sql(
                "SELECT * FROM candles_5min WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                conn, params=(pos["symbol"],),
            )
            if len(df) == 0:
                still_open.append(pos)
                continue
            ltp = float(df.iloc[0]["close"])
            reason = None
            if ltp <= pos["stop_loss"]:
                reason = "sl"
            elif ltp >= pos["target"]:
                reason = "target"
            elif now >= datetime.fromisoformat(pos["expires_at"]):
                reason = "time"

            if reason:
                pnl_pct = (ltp - pos["entry"]) / pos["entry"] * 100
                self.paper_pnl_pct += pnl_pct
                closed = {**pos, "exit": ltp, "pnl_pct": round(pnl_pct, 3),
                          "exit_reason": reason, "closed_at": now.isoformat()}
                self.paper_trades_closed.append(closed)
                logger.info(f"[MLScore] 📄 PAPER EXIT {pos['symbol']} @ ₹{ltp} "
                            f"({reason}) P&L={pnl_pct:+.2f}%")
            else:
                still_open.append(pos)

        self.paper_positions = still_open
        conn.close()

    async def _close_all_paper(self, reason: str):
        for pos in list(self.paper_positions):
            pos["expires_at"] = datetime.now(_IST).isoformat()
        await self._manage_paper_positions()

    # ------------------------------------------------------------------ misc

    @staticmethod
    def _is_market_hours(now: datetime) -> bool:
        if now.weekday() >= 5:
            return False
        t = now.time()
        return (t >= datetime.strptime("09:15", "%H:%M").time()
                and t <= datetime.strptime("15:30", "%H:%M").time())

    async def update_live_candles(self):
        """Append the latest 5-min candles to DB so scoring stays current."""
        from backend.dependencies import get_angel_client
        client = get_angel_client()
        conn = get_db()
        now = datetime.now(_IST)
        frm = (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        to = now.strftime("%Y-%m-%d %H:%M")

        for i, symbol in enumerate(LIVE_UNIVERSE):
            try:
                token = client.search_scrip("NSE", symbol)
                if not token:
                    continue
                df = client.get_historical_data("NSE", token, "FIVE_MINUTE", frm, to)
                if df is not None and len(df):
                    df = df.copy()
                    df["symbol"] = symbol
                    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
                    rows = df[["symbol", "timestamp", "open", "high", "low", "close", "volume"]].values.tolist()
                    conn.executemany("INSERT OR REPLACE INTO candles_5min VALUES (?,?,?,?,?,?,?)", rows)
                    conn.commit()
                await asyncio.sleep(1.2)  # Angel One rate limit: 1+ second between requests
            except Exception as e:
                logger.debug(f"[MLScore] live candle update {symbol} failed: {e}")

        # NIFTY index
        try:
            df = client.get_historical_data("NSE", "26000", "FIVE_MINUTE", frm, to)
            if df is not None and len(df):
                df = df.copy()
                df["symbol"] = "NIFTY50"
                df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S")
                rows = df[["symbol", "timestamp", "open", "high", "low", "close", "volume"]].values.tolist()
                conn.executemany("INSERT OR REPLACE INTO index_candles_5min VALUES (?,?,?,?,?,?,?)", rows)
                conn.commit()
        except Exception as e:
            logger.debug(f"[MLScore] NIFTY update failed: {e}")
        conn.close()

    def get_status(self) -> Dict:
        wins = [t for t in self.paper_trades_closed if t["pnl_pct"] > 0]
        return {
            "model_loaded": self.model is not None,
            "model_version": self.meta.get("model_version"),
            "tradeable": self.meta.get("tradeable", False),
            "threshold": self.threshold,
            "last_update": self.last_update,
            "stocks_tracked": len(LIVE_UNIVERSE),
            "features_calculated": len(FEATURE_COLS),
            "signals_active": len(self.active_signals),
            "enabled": self.enabled,
            "mode": self.mode,
            "paper_positions": self.paper_positions,
            "paper_trades_today": len(self.paper_trades_closed),
            "paper_win_rate": round(len(wins) / len(self.paper_trades_closed), 3) if self.paper_trades_closed else 0,
            "paper_pnl_pct": round(self.paper_pnl_pct, 3),
            "test_expectancy": (self.meta.get("test_report") or {}).get("expectancy"),
        }
