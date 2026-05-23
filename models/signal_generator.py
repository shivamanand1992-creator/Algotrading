"""
Signal generator — combines market regime + price prediction into actionable options signals.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import pandas as pd
import numpy as np
from loguru import logger
import pytz

IST = pytz.timezone("Asia/Kolkata")


@dataclass
class Signal:
    action: str                    # BUY_CE | BUY_PE | SELL_STRADDLE | SELL_STRANGLE | NO_TRADE
    strike: int = 0
    option_type: str = ""          # CE | PE | BOTH
    expiry: str = ""
    symbol: str = ""
    token: str = ""
    exchange: str = "NFO"
    qty: int = 50
    price: float = 0.0
    sl_price: float = 0.0
    target_price: float = 0.0
    confidence: float = 0.0
    regime: str = "unknown"
    prediction: int = 0            # -1, 0, +1
    reasons: list = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(IST))


class SignalGenerator:
    """
    Combines MarketRegimeClassifier + PriceDirectionPredictor
    to produce actionable trading signals with full entry details.
    """

    def __init__(self, regime_classifier, price_predictor, config: dict):
        self.regime_clf = regime_classifier
        self.price_pred = price_predictor
        self.config = config
        self.min_confidence = config["ml"]["price_predictor"]["min_confidence"]
        self.risk_cfg = config["risk"]
        self.lot_size = config["trading"]["lot_size"]
        self._feature_cols: list[str] = []   # populated after first call

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame, chain_df: Optional[pd.DataFrame] = None) -> Signal:
        """
        Generate a trading signal from feature-enriched OHLCV DataFrame.

        Parameters
        ----------
        df        : Feature-enriched DataFrame (output of TechnicalFeatureEngine.compute_all)
        chain_df  : Optional options chain DataFrame (output of OptionsChainAnalyzer.build_option_chain_df)

        Returns
        -------
        Signal dataclass
        """
        no_trade = Signal(action="NO_TRADE")

        if df.empty or len(df) < 30:
            return no_trade

        try:
            regime, regime_conf = self._get_regime(df)
        except Exception as e:
            logger.warning(f"Regime detection failed: {e}")
            regime, regime_conf = "unknown", 0.0

        try:
            direction, pred_conf, probs = self._get_price_direction(df)
        except Exception as e:
            logger.warning(f"Price prediction failed, using rule-based: {e}")
            direction, pred_conf, probs = self._rule_based_direction(df)

        # Combined confidence — geometric mean
        combined_conf = float(np.sqrt(regime_conf * pred_conf)) if regime_conf > 0 and pred_conf > 0 else pred_conf
        logger.debug(f"Regime: {regime} ({regime_conf:.0%}) | Direction: {direction} ({pred_conf:.0%}) | Combined: {combined_conf:.0%}")

        if combined_conf < self.min_confidence:
            return Signal(action="NO_TRADE", regime=regime, confidence=combined_conf,
                         reasons=[f"Confidence {combined_conf:.0%} below threshold {self.min_confidence:.0%}"])

        action, option_type, reasons = self._decide_action(regime, direction, df, chain_df)

        if action == "NO_TRADE":
            return Signal(action="NO_TRADE", regime=regime, confidence=combined_conf, reasons=reasons)

        signal = Signal(
            action=action,
            option_type=option_type,
            exchange="NFO",
            qty=self.lot_size,
            confidence=combined_conf,
            regime=regime,
            prediction=direction,
            reasons=reasons,
        )
        return signal

    def compute_entry_details(self, signal: Signal, spot_price: float, chain_df: Optional[pd.DataFrame]) -> Signal:
        """
        Fill in strike, expiry, symbol, token, price, sl_price, target_price
        from spot price and options chain.
        """
        from data.options_chain import OptionsChainAnalyzer
        analyzer = OptionsChainAnalyzer()

        atm = analyzer.get_atm_strike(spot_price)
        expiry = analyzer.get_nearest_expiry()
        signal.expiry = expiry

        if signal.action in ("BUY_CE", "BUY_PE"):
            signal.strike = atm
            opt_type = "CE" if signal.action == "BUY_CE" else "PE"
            signal.option_type = opt_type

            # Estimate premium from chain or Black-Scholes
            premium = self._get_option_premium(atm, opt_type, spot_price, chain_df)
            signal.price = premium
            signal.sl_price = round(premium * (1 - self.risk_cfg["option_buy_sl_pct"]), 2)
            signal.target_price = round(premium * (1 + self.risk_cfg["option_buy_target_pct"]), 2)

            # Build symbol name for Angel One
            expiry_tag = self._format_expiry_tag(expiry)
            signal.symbol = f"NIFTY{expiry_tag}{atm}{opt_type}"

        elif signal.action in ("SELL_STRADDLE", "SELL_STRANGLE"):
            signal.strike = atm
            signal.option_type = "BOTH"
            # For straddle/strangle, price = combined premium received
            ce_prem = self._get_option_premium(atm, "CE", spot_price, chain_df)
            pe_prem = self._get_option_premium(atm, "PE", spot_price, chain_df)
            signal.price = ce_prem + pe_prem
            signal.sl_price = round(signal.price * (1 + self.risk_cfg["option_sell_sl_pct"]), 2)
            signal.target_price = round(signal.price * 0.50, 2)   # 50% decay target
            signal.symbol = f"NIFTY{self._format_expiry_tag(expiry)}{atm}STRADDLE"

        return signal

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_regime(self, df: pd.DataFrame) -> tuple[str, float]:
        """Get market regime via classifier or rule-based fallback."""
        try:
            from features.market_regime import MarketRegimeDetector
            feat_cols = self._get_regime_feature_cols(df)
            if feat_cols and hasattr(self.regime_clf, "model") and self.regime_clf.model is not None:
                regime, conf = self.regime_clf.get_current_regime(df)
                return regime, conf
        except Exception:
            pass
        # Rule-based fallback
        from features.market_regime import MarketRegimeDetector
        detector = MarketRegimeDetector()
        regime = detector.detect_regime_rules(df)
        return regime, 0.75   # Fixed confidence for rule-based

    def _get_price_direction(self, df: pd.DataFrame) -> tuple[int, float, dict]:
        """Get price direction via predictor or fallback."""
        feat_cols = self._get_predictor_feature_cols(df)
        if feat_cols and hasattr(self.price_pred, "is_trained") and self.price_pred.is_trained:
            return self.price_pred.predict(df, feat_cols)
        return self._rule_based_direction(df)

    def _rule_based_direction(self, df: pd.DataFrame) -> tuple[int, float, dict]:
        """Deterministic direction from EMA + RSI + MACD."""
        latest = df.iloc[-1]
        score = 0
        count = 0

        ema9 = latest.get("ema_9", np.nan)
        ema21 = latest.get("ema_21", np.nan)
        if not (np.isnan(ema9) or np.isnan(ema21)):
            score += 1 if ema9 > ema21 else -1
            count += 1

        rsi = latest.get("rsi", np.nan)
        if not np.isnan(rsi):
            if rsi > 55:
                score += 1
            elif rsi < 45:
                score -= 1
            count += 1

        macd_hist = latest.get("macd_histogram", np.nan)
        if not np.isnan(macd_hist):
            score += 1 if macd_hist > 0 else -1
            count += 1

        if count == 0:
            return 0, 0.0, {"up": 0.33, "flat": 0.34, "down": 0.33}

        norm = score / count    # -1 to +1
        direction = 1 if norm > 0.3 else (-1 if norm < -0.3 else 0)
        confidence = abs(norm) * 0.65 + 0.30   # map to [0.30, 0.95]
        probs = {
            "up": max(0, norm) / 2 + 0.33,
            "flat": 0.33 * (1 - abs(norm)),
            "down": max(0, -norm) / 2 + 0.33,
        }
        return direction, float(confidence), probs

    def _decide_action(
        self, regime: str, direction: int, df: pd.DataFrame, chain_df: Optional[pd.DataFrame]
    ) -> tuple[str, str, list]:
        """Map regime + direction to a concrete options action."""
        reasons = [f"Regime: {regime}", f"Price direction: {direction:+d}"]

        if regime in ("trending_up", "trending_down"):
            if direction == 1:
                reasons.append("Trend + bullish signal → BUY CE")
                return "BUY_CE", "CE", reasons
            elif direction == -1:
                reasons.append("Trend + bearish signal → BUY PE")
                return "BUY_PE", "PE", reasons
            else:
                reasons.append("Trend detected but direction unclear")
                return "NO_TRADE", "", reasons

        elif regime == "ranging":
            iv_ok = self._check_iv_for_selling(chain_df)
            if iv_ok:
                reasons.append("Ranging market + elevated IV → SELL STRADDLE")
                return "SELL_STRADDLE", "BOTH", reasons
            else:
                reasons.append("Ranging but IV too low for premium selling")
                return "NO_TRADE", "", reasons

        elif regime == "high_volatility":
            if direction == 1:
                reasons.append("High vol + bullish → BUY CE (ATM, small size)")
                return "BUY_CE", "CE", reasons
            elif direction == -1:
                reasons.append("High vol + bearish → BUY PE (ATM, small size)")
                return "BUY_PE", "PE", reasons
            else:
                return "NO_TRADE", "", reasons

        reasons.append(f"Unknown regime: {regime}")
        return "NO_TRADE", "", reasons

    def _check_iv_for_selling(self, chain_df: Optional[pd.DataFrame]) -> bool:
        """Returns True if IV conditions are suitable for premium selling."""
        if chain_df is None or chain_df.empty:
            return False
        try:
            avg_iv = chain_df[["ce_iv", "pe_iv"]].mean().mean()
            return avg_iv > 12.0   # IV% threshold
        except Exception:
            return False

    def _get_option_premium(
        self, strike: int, opt_type: str, spot: float, chain_df: Optional[pd.DataFrame]
    ) -> float:
        """Get option premium from chain or estimate via Black-Scholes."""
        if chain_df is not None and not chain_df.empty:
            row = chain_df[chain_df["strike"] == strike]
            if not row.empty:
                col = "ce_ltp" if opt_type == "CE" else "pe_ltp"
                val = row.iloc[0].get(col, 0)
                if val > 0:
                    return float(val)

        # Black-Scholes fallback
        return self._bs_price(spot, strike, opt_type, dte=7, iv=0.15)

    @staticmethod
    def _bs_price(S: float, K: int, opt_type: str, dte: float = 7, iv: float = 0.15) -> float:
        """Simplified Black-Scholes option price."""
        import math
        from scipy.stats import norm
        T = max(dte / 252, 1e-6)
        r = 0.065
        d1 = (math.log(S / K) + (r + 0.5 * iv**2) * T) / (iv * math.sqrt(T))
        d2 = d1 - iv * math.sqrt(T)
        if opt_type == "CE":
            return max(S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2), 0.05)
        return max(K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1), 0.05)

    @staticmethod
    def _format_expiry_tag(expiry: str) -> str:
        """Convert 'DD-MMM-YYYY' → 'DDMMMYYYY' uppercase for symbol name."""
        return expiry.replace("-", "").upper()

    def _get_regime_feature_cols(self, df: pd.DataFrame) -> list[str]:
        wanted = ["adx", "atr_pct", "rsi", "macd_histogram", "bb_width",
                  "ema_9", "ema_21", "volume"]
        return [c for c in wanted if c in df.columns]

    def _get_predictor_feature_cols(self, df: pd.DataFrame) -> list[str]:
        exclude = {"open", "high", "low", "close", "volume", "date"}
        return [c for c in df.columns if c not in exclude and df[c].dtype in (float, int, "float64", "int64")]
