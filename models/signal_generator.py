"""
signal_generator.py
===================
Combines MarketRegimeClassifier + PriceDirectionPredictor outputs into
actionable options trading signals for Nifty50 intraday.

Signal actions
--------------
BUY_CE          — Buy a Call option (trend-following long)
BUY_PE          — Buy a Put option (trend-following short)
SELL_STRADDLE   — Sell ATM CE + PE simultaneously (premium selling)
NO_TRADE        — No actionable setup detected

Decision matrix
---------------
Regime           | Prediction | Confidence | Action
─────────────────┼────────────┼────────────┼──────────────────────────────
trending_up      | up  (+1)   | ≥ 0.65     | BUY_CE  (ATM or OTM+1)
trending_down    | down (-1)  | ≥ 0.65     | BUY_PE  (ATM or OTM-1)
ranging          | any        | ≥ 0.65     | SELL_STRADDLE (if IV is high)
high_volatility  | up  (+1)   | ≥ 0.65     | BUY_CE  (ATM only, small size)
high_volatility  | down (-1)  | ≥ 0.65     | BUY_PE  (ATM only, small size)
─── (confidence below threshold) ────────────────── NO_TRADE ────────────
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz
from loguru import logger
from scipy.stats import norm

from models.price_predictor import PriceDirectionPredictor
from models.regime_classifier import MarketRegimeClassifier

# ---------------------------------------------------------------------------
# Module-level India VIX cache (1-hour TTL) — avoids repeated yfinance calls
# ---------------------------------------------------------------------------
_vix_cache: dict = {"series": None, "ts": 0.0}
_VIX_CACHE_TTL = 3600  # seconds


def _get_vix_percentile() -> Optional[float]:
    """
    Fetch 1 year of India VIX (^INDIAVIX) from Yahoo Finance and return
    the percentile rank of the latest reading vs the full history.
    Returns None on any failure.
    """
    global _vix_cache
    try:
        now = time.time()
        if _vix_cache["series"] is not None and (now - _vix_cache["ts"]) < _VIX_CACHE_TTL:
            vix_series = _vix_cache["series"]
        else:
            import yfinance as yf
            df = yf.Ticker("^INDIAVIX").history(period="365d", interval="1d")
            if df is None or df.empty:
                return None
            vix_series = df["Close"].dropna()
            if len(vix_series) < 20:
                return None
            _vix_cache["series"] = vix_series
            _vix_cache["ts"] = now

        current_vix = float(vix_series.iloc[-1])
        percentile = float((vix_series < current_vix).mean() * 100)
        logger.debug(f"India VIX: {current_vix:.2f} → percentile={percentile:.1f}%")
        return percentile
    except Exception as e:
        logger.debug(f"VIX percentile fetch failed: {e}")
        return None

IST = pytz.timezone("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_NIFTY_STRIKE_STEP = 50          # Nifty50 strikes are in multiples of 50
_DEFAULT_LOT_SIZE = 50           # Nifty50 lot size
_MIN_CONFIDENCE = 0.65           # Default minimum confidence threshold
_HIGH_IV_PERCENTILE_THRESHOLD = 60.0  # IV percentile above which IV is "high"


# =============================================================================
# Signal dataclass
# =============================================================================

@dataclass
class Signal:
    """
    Actionable options trading signal produced by SignalGenerator.

    Fields
    ------
    action          : str   — 'BUY_CE' | 'BUY_PE' | 'SELL_STRADDLE' | 'NO_TRADE'
    strike          : int   — selected strike price (0 for NO_TRADE)
    expiry          : str   — expiry date string e.g. "25-MAY-2026"
    confidence      : float — ensemble confidence [0, 1]
    regime          : str   — detected market regime
    direction       : int   — predicted direction: +1 (up), -1 (down), 0 (flat)
    reasons         : list  — human-readable explanation strings
    spot_price      : float — Nifty50 spot price at signal time
    estimated_premium: float— estimated option premium (0 if unknown)
    position_size   : int   — number of lots recommended
    is_small_size   : bool  — True when high_volatility regime (reduced size)
    timestamp       : datetime — signal generation time (IST-aware)
    regime_probs    : dict  — {'trending_up': p, 'ranging': p, ...}
    direction_probs : dict  — {'up': p, 'flat': p, 'down': p}

    Properties
    ----------
    is_actionable   : bool  — True unless action == 'NO_TRADE'
    is_buy          : bool  — True for BUY_CE / BUY_PE
    is_sell         : bool  — True for SELL_STRADDLE
    option_type     : str   — 'CE' | 'PE' | 'STRADDLE' | ''
    """

    action: str
    strike: int = 0
    expiry: str = ""
    confidence: float = 0.0
    regime: str = "unknown"
    direction: int = 0
    reasons: List[str] = field(default_factory=list)
    spot_price: float = 0.0
    estimated_premium: float = 0.0
    position_size: int = 1
    is_small_size: bool = False
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(IST)
    )
    regime_probs: Dict[str, float] = field(default_factory=dict)
    direction_probs: Dict[str, float] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def is_actionable(self) -> bool:
        """True for any signal that requires actual order placement."""
        return self.action != "NO_TRADE"

    @property
    def is_buy(self) -> bool:
        return self.action in ("BUY_CE", "BUY_PE")

    @property
    def is_sell(self) -> bool:
        return self.action == "SELL_STRADDLE"

    @property
    def option_type(self) -> str:
        if self.action == "BUY_CE":
            return "CE"
        if self.action == "BUY_PE":
            return "PE"
        if self.action == "SELL_STRADDLE":
            return "STRADDLE"
        return ""

    def __str__(self) -> str:
        return (
            f"Signal({self.action} | strike={self.strike} | expiry={self.expiry} | "
            f"conf={self.confidence:.3f} | regime={self.regime} | "
            f"dir={self.direction:+d} | size={self.position_size}lot"
            f"{'[small]' if self.is_small_size else ''})"
        )


# ---------------------------------------------------------------------------
# No-trade factory
# ---------------------------------------------------------------------------

def _no_trade(
    regime: str,
    direction: int,
    spot_price: float,
    reason: str,
    confidence: float = 0.0,
    regime_probs: Optional[Dict[str, float]] = None,
    direction_probs: Optional[Dict[str, float]] = None,
) -> Signal:
    return Signal(
        action="NO_TRADE",
        strike=0,
        expiry="",
        confidence=confidence,
        regime=regime,
        direction=direction,
        reasons=[reason],
        spot_price=spot_price,
        regime_probs=regime_probs or {},
        direction_probs=direction_probs or {},
    )


# =============================================================================
# Signal Generator
# =============================================================================

class SignalGenerator:
    """
    Combines regime + price-direction predictions into actionable options signals.

    Usage
    -----
    gen = SignalGenerator(regime_classifier, price_predictor, config)
    signal = gen.generate_signal(df, options_data=chain_df)
    """

    def __init__(
        self,
        regime_classifier: MarketRegimeClassifier,
        price_predictor: PriceDirectionPredictor,
        config: dict,
    ) -> None:
        """
        Parameters
        ----------
        regime_classifier : MarketRegimeClassifier
            Trained regime classifier (must have been trained or loaded).
        price_predictor : PriceDirectionPredictor
            Trained price-direction predictor.
        config : dict
            Full application configuration.
        """
        self.regime_clf = regime_classifier
        self.price_pred = price_predictor
        self.config = config

        ml_cfg = config.get("ml", {})
        pp_cfg = ml_cfg.get("price_predictor", {})
        self.min_confidence: float = float(
            pp_cfg.get("min_confidence", _MIN_CONFIDENCE)
        )

        trading_cfg = config.get("trading", {})
        self.lot_size: int = int(trading_cfg.get("lot_size", _DEFAULT_LOT_SIZE))
        self.max_lots: int = int(trading_cfg.get("max_lots_per_trade", 2))
        self.strike_step: int = _NIFTY_STRIKE_STEP

        # Risk config for SL/target calculations
        self.risk_cfg: dict = config.get("risk", {})

        # IV percentile threshold above which "high IV" SELL_STRADDLE is considered
        strategy_cfg = config.get("strategies", {}).get("premium_selling", {})
        self.high_iv_percentile: float = float(
            strategy_cfg.get("min_iv_percentile", _HIGH_IV_PERCENTILE_THRESHOLD)
        )

        logger.info(
            f"SignalGenerator initialised. "
            f"min_confidence={self.min_confidence}, "
            f"lot_size={self.lot_size}, max_lots={self.max_lots}"
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def generate_signal(
        self,
        df: pd.DataFrame,
        options_data: Optional[pd.DataFrame] = None,
        feature_cols: Optional[List[str]] = None,
    ) -> Signal:
        """
        Analyse the most recent market data and generate a trading signal.

        Parameters
        ----------
        df : pd.DataFrame
            Feature-enriched OHLCV DataFrame.  Must have at least
            `lookback` rows and contain all regime + price-predictor
            feature columns.
        options_data : pd.DataFrame, optional
            Current option chain snapshot.  Expected columns:
              strike, option_type (CE/PE), ltp, iv, oi, volume
            Used to determine expiry, fill in premium estimates, and
            check IV levels for straddle signals.
        feature_cols : list of str, optional
            Feature column names for the price predictor.  If None, uses
            the predictor's stored self.price_pred.feature_cols.

        Returns
        -------
        Signal
        """
        # Resolve feature columns
        feat_cols = feature_cols or self.price_pred.feature_cols
        if feat_cols is None:
            logger.warning(
                "No feature_cols supplied and price_predictor has none stored. "
                "Returning NO_TRADE."
            )
            spot = _latest_close(df)
            return _no_trade("unknown", 0, spot, "Feature columns not configured")

        if df is None or df.empty or len(df) < self.price_pred.lookback:
            spot = _latest_close(df) if df is not None and not df.empty else 0.0
            return _no_trade(
                "unknown", 0, spot,
                f"Insufficient data: need {self.price_pred.lookback} rows, "
                f"got {len(df) if df is not None else 0}",
            )

        spot_price = _latest_close(df)

        # ── Regime classification ──────────────────────────────────────
        try:
            regime, regime_conf, regime_probs = self.regime_clf.predict(df)
        except Exception as exc:
            logger.error(f"Regime prediction failed: {exc}")
            return _no_trade("unknown", 0, spot_price, f"Regime error: {exc}")

        # ── Price direction prediction ─────────────────────────────────
        try:
            direction, price_conf, direction_probs = self.price_pred.predict(
                df, feat_cols
            )
        except Exception as exc:
            logger.error(f"Price direction prediction failed: {exc}")
            return _no_trade(
                regime, 0, spot_price, f"Price prediction error: {exc}",
                regime_probs=regime_probs,
            )

        # ── Ensemble confidence: geometric mean of both model confidences ─
        combined_confidence = float(np.sqrt(regime_conf * price_conf))

        logger.info(
            f"SignalGenerator: regime={regime}(conf={regime_conf:.3f}), "
            f"direction={direction:+d}(conf={price_conf:.3f}), "
            f"combined_conf={combined_confidence:.3f}"
        )

        # ── Confidence gate ────────────────────────────────────────────
        if combined_confidence < self.min_confidence:
            return _no_trade(
                regime, direction, spot_price,
                f"Combined confidence {combined_confidence:.3f} < "
                f"threshold {self.min_confidence:.3f}",
                confidence=combined_confidence,
                regime_probs=regime_probs,
                direction_probs=direction_probs,
            )

        # ── Decision logic ─────────────────────────────────────────────
        reasons: List[str] = [
            f"Regime: {regime} (conf={regime_conf:.3f})",
            f"Direction: {_dir_label(direction)} (conf={price_conf:.3f})",
            f"Combined confidence: {combined_confidence:.3f}",
        ]

        # Determine IV environment from options data
        iv_is_high = self._check_high_iv(options_data, spot_price)

        action, strike, is_small_size, extra_reasons = self._apply_decision_logic(
            regime=regime,
            direction=direction,
            spot_price=spot_price,
            iv_is_high=iv_is_high,
            options_data=options_data,
        )
        reasons.extend(extra_reasons)

        if action == "NO_TRADE":
            return _no_trade(
                regime, direction, spot_price,
                "; ".join(reasons),
                confidence=combined_confidence,
                regime_probs=regime_probs,
                direction_probs=direction_probs,
            )

        # ── Expiry + premium details ───────────────────────────────────
        expiry = self._resolve_expiry(options_data)
        position_size = self._size_positions(is_small_size)

        signal = Signal(
            action=action,
            strike=strike,
            expiry=expiry,
            confidence=combined_confidence,
            regime=regime,
            direction=direction,
            reasons=reasons,
            spot_price=spot_price,
            estimated_premium=0.0,   # filled by compute_entry_details below
            position_size=position_size,
            is_small_size=is_small_size,
            regime_probs=regime_probs,
            direction_probs=direction_probs,
        )

        # Fill in estimated premium if chain is available
        if options_data is not None and not options_data.empty:
            signal = self.compute_entry_details(signal, spot_price, options_data)

        logger.info(f"Generated: {signal}")
        for r in signal.reasons:
            logger.debug(f"  Reason: {r}")

        return signal

    # ------------------------------------------------------------------
    # Decision logic
    # ------------------------------------------------------------------

    def _apply_decision_logic(
        self,
        regime: str,
        direction: int,
        spot_price: float,
        iv_is_high: bool,
        options_data: Optional[pd.DataFrame],
    ) -> Tuple[str, int, bool, List[str]]:
        """
        Core decision rules.

        Returns
        -------
        action        : str  — 'BUY_CE' | 'BUY_PE' | 'SELL_STRADDLE' | 'NO_TRADE'
        strike        : int  — chosen strike (0 for NO_TRADE)
        is_small_size : bool — True for high-volatility reduced sizing
        reasons       : list[str] — additional human-readable reason strings
        """
        reasons: List[str] = []
        atm = _round_to_strike(spot_price, self.strike_step)

        # ── trending_up + predict up → BUY_CE (ATM or OTM+1) ──────────
        if regime == "trending_up" and direction == 1:
            strike = atm + self.strike_step  # OTM+1 for better reward/risk
            reasons.append(
                f"Trend UP + direction UP → BUY_CE at OTM+1 strike {strike}"
            )
            return "BUY_CE", strike, False, reasons

        # ── trending_down + predict down → BUY_PE (ATM or OTM-1) ──────
        if regime == "trending_down" and direction == -1:
            strike = atm - self.strike_step  # OTM-1 for better reward/risk
            reasons.append(
                f"Trend DOWN + direction DOWN → BUY_PE at OTM-1 strike {strike}"
            )
            return "BUY_PE", strike, False, reasons

        # ── ranging + high IV → SELL_STRADDLE ─────────────────────────
        if regime == "ranging":
            if iv_is_high:
                reasons.append(
                    f"RANGING regime + high IV → SELL_STRADDLE at ATM {atm}"
                )
                return "SELL_STRADDLE", atm, False, reasons
            else:
                reasons.append(
                    "RANGING regime but IV not elevated — skipping SELL_STRADDLE"
                )
                return "NO_TRADE", 0, False, reasons

        # ── high_volatility + predict up → BUY_CE (ATM, small size) ───
        if regime == "high_volatility" and direction == 1:
            reasons.append(
                f"HIGH VOLATILITY + direction UP → BUY_CE at ATM {atm} (small size)"
            )
            return "BUY_CE", atm, True, reasons

        # ── high_volatility + predict down → BUY_PE (ATM, small size) ─
        if regime == "high_volatility" and direction == -1:
            reasons.append(
                f"HIGH VOLATILITY + direction DOWN → BUY_PE at ATM {atm} (small size)"
            )
            return "BUY_PE", atm, True, reasons

        # ── Directional signal but mismatched regime/direction ─────────
        reasons.append(
            f"No actionable setup: regime={regime}, direction={direction:+d}"
        )
        return "NO_TRADE", 0, False, reasons

    # ------------------------------------------------------------------
    # Entry details
    # ------------------------------------------------------------------

    def compute_entry_details(
        self,
        signal: Signal,
        spot_price: float,
        chain_df: pd.DataFrame,
    ) -> Signal:
        """
        Enrich a Signal with strike confirmation, expiry, and estimated premium.

        The option chain DataFrame is expected to have at minimum:
          strike (int/float), option_type (str: 'CE'|'PE'),
          ltp (float), expiry (str), iv (float)

        If the chain doesn't contain the signal's strike, the method falls
        back to the nearest available strike.  When no chain is available,
        the premium is estimated via a simplified Black-Scholes model.

        Parameters
        ----------
        signal     : Signal   — signal to enrich (mutated in-place)
        spot_price : float    — current Nifty50 spot price
        chain_df   : pd.DataFrame — options chain snapshot

        Returns
        -------
        Signal  — the same Signal with estimated_premium and confirmed
                  expiry / strike.
        """
        if chain_df is None or chain_df.empty:
            # Black-Scholes fallback for premium estimate
            signal.estimated_premium = self._estimate_premium_bs(
                spot_price, signal.strike or _round_to_strike(spot_price),
                signal.option_type, days_to_expiry=7,
            )
            return signal

        # Normalise column names to lower-case
        chain = chain_df.copy()
        chain.columns = [c.lower().strip() for c in chain.columns]

        # Determine which leg(s) to look up
        if signal.action == "BUY_CE":
            legs = [("CE", signal.strike)]
        elif signal.action == "BUY_PE":
            legs = [("PE", signal.strike)]
        elif signal.action == "SELL_STRADDLE":
            legs = [("CE", signal.strike), ("PE", signal.strike)]
        else:
            return signal

        total_premium = 0.0
        resolved_strike = signal.strike
        resolved_expiry = signal.expiry or self._resolve_expiry(chain_df)

        for opt_type, target_strike in legs:
            # Filter to this option type
            subset = chain[chain["option_type"].str.upper() == opt_type].copy() \
                if "option_type" in chain.columns else chain.copy()

            if subset.empty:
                # Fall back to BS estimate for this leg
                total_premium += self._estimate_premium_bs(
                    spot_price, target_strike, opt_type, days_to_expiry=7
                )
                continue

            # Snap to nearest available strike in chain
            if "strike" in subset.columns:
                available_strikes = subset["strike"].astype(float).values
                nearest_idx = int(np.argmin(np.abs(available_strikes - target_strike)))
                nearest_strike = int(available_strikes[nearest_idx])
                row = subset.iloc[[nearest_idx]]
            else:
                row = subset.head(1)
                nearest_strike = target_strike

            # Extract LTP
            ltp = 0.0
            for ltp_col in ("ltp", "last_price", "close"):
                if ltp_col in row.columns:
                    val = pd.to_numeric(row[ltp_col].iloc[0], errors="coerce")
                    if not np.isnan(val) and val > 0:
                        ltp = float(val)
                        break

            if ltp == 0.0:
                ltp = self._estimate_premium_bs(
                    spot_price, nearest_strike, opt_type, days_to_expiry=7
                )

            total_premium += ltp

            # Resolve expiry from chain if not yet set
            if resolved_expiry == "" and "expiry" in row.columns:
                resolved_expiry = str(row["expiry"].iloc[0])

            resolved_strike = nearest_strike

        signal.strike = resolved_strike
        signal.expiry = resolved_expiry
        signal.estimated_premium = round(total_premium, 2)

        logger.debug(
            f"compute_entry_details: strike={resolved_strike}, "
            f"expiry={resolved_expiry}, premium={total_premium:.2f}"
        )
        return signal

    # ------------------------------------------------------------------
    # Black-Scholes premium estimate (fallback when chain unavailable)
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_premium_bs(
        spot: float,
        strike: int,
        opt_type: str,
        days_to_expiry: float = 7,
        iv: float = 0.15,
        risk_free_rate: float = 0.065,
    ) -> float:
        """
        Simplified Black-Scholes call/put price.

        Parameters
        ----------
        spot            : float  — current spot price
        strike          : int    — option strike
        opt_type        : str    — 'CE' or 'PE'
        days_to_expiry  : float  — calendar days to expiry
        iv              : float  — implied volatility (annualised fraction)
        risk_free_rate  : float  — annual risk-free rate

        Returns
        -------
        float — estimated option premium
        """
        T = max(days_to_expiry / 365.0, 1e-6)
        S, K = float(spot), float(strike)
        r, sigma = risk_free_rate, iv

        try:
            d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (
                sigma * math.sqrt(T)
            )
            d2 = d1 - sigma * math.sqrt(T)

            if opt_type.upper() == "CE":
                price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
            else:  # PE
                price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

            return max(round(float(price), 2), 0.05)
        except Exception:
            # Intrinsic value fallback
            if opt_type.upper() == "CE":
                return max(round(S - K, 2), 0.05)
            return max(round(K - S, 2), 0.05)

    # ------------------------------------------------------------------
    # IV environment helper
    # ------------------------------------------------------------------

    def _check_high_iv(
        self,
        options_data: Optional[pd.DataFrame],
        spot_price: float,
    ) -> bool:
        """
        Returns True if the current IV environment is "high" — i.e. the
        median IV of the nearest ATM options exceeds the historical
        `high_iv_percentile` threshold stored in this instance.

        Falls back to False if no options data is available.
        """
        if options_data is None or options_data.empty:
            # Fall back to India VIX percentile as a proxy for overall IV level
            vix_pct = _get_vix_percentile()
            if vix_pct is not None:
                is_high = vix_pct >= self.high_iv_percentile
                logger.debug(
                    f"No options chain — using India VIX percentile={vix_pct:.1f}% "
                    f"(threshold={self.high_iv_percentile:.0f}%) → high_iv={is_high}"
                )
                return is_high
            logger.debug("No options data and VIX fetch failed — assuming IV is not high.")
            return False

        chain = options_data.copy()
        chain.columns = [c.lower().strip() for c in chain.columns]

        # Try various common IV column names
        iv_col = None
        for candidate in ("iv", "implied_volatility", "ce_iv", "pe_iv"):
            if candidate in chain.columns:
                iv_col = candidate
                break

        if iv_col is None:
            logger.debug("Option chain missing IV column — assuming IV not high.")
            return False

        atm = _round_to_strike(spot_price, self.strike_step)

        # ATM ± 2 strikes
        near_strikes = [
            atm - 2 * self.strike_step, atm - self.strike_step,
            atm, atm + self.strike_step, atm + 2 * self.strike_step,
        ]

        if "strike" in chain.columns:
            near = chain[chain["strike"].astype(float).round().astype(int).isin(near_strikes)]
        else:
            near = chain

        if near.empty:
            near = chain

        iv_series = pd.to_numeric(near[iv_col], errors="coerce").dropna()
        if iv_series.empty:
            return False

        median_iv = float(iv_series.median())
        all_iv = pd.to_numeric(chain[iv_col], errors="coerce").dropna()
        if all_iv.empty:
            return False

        percentile_val = float(np.percentile(all_iv, self.high_iv_percentile))
        is_high = median_iv >= percentile_val

        logger.debug(
            f"IV check: ATM-zone median IV={median_iv:.2f}, "
            f"p{self.high_iv_percentile:.0f}={percentile_val:.2f} → "
            f"high_iv={is_high}"
        )
        return is_high

    # ------------------------------------------------------------------
    # Expiry resolution
    # ------------------------------------------------------------------

    def _resolve_expiry(
        self,
        options_data: Optional[pd.DataFrame],
    ) -> str:
        """
        Determine the nearest weekly expiry from the options chain.

        If no chain is available (or the chain lacks an expiry column),
        falls back to computing the next Thursday's date (Nifty weekly
        expiry) in "DD-MMM-YYYY" format.

        Parameters
        ----------
        options_data : pd.DataFrame or None

        Returns
        -------
        str  — expiry date e.g. "29-MAY-2026"
        """
        if options_data is not None and not options_data.empty:
            chain = options_data.copy()
            chain.columns = [c.lower().strip() for c in chain.columns]
            if "expiry" in chain.columns:
                expiries = chain["expiry"].dropna().unique()
                if len(expiries) > 0:
                    parsed: List[Tuple[datetime, str]] = []
                    for e in expiries:
                        try:
                            dt = pd.to_datetime(str(e), dayfirst=True)
                            if dt.tzinfo is None:
                                dt = dt.tz_localize(IST)
                            parsed.append((dt, str(e)))
                        except Exception:
                            pass
                    if parsed:
                        parsed.sort(key=lambda x: x[0])
                        return parsed[0][1]

        # Fallback: compute next Thursday from today (IST)
        now = datetime.now(IST)
        days_ahead = 3 - now.weekday()  # Thursday is weekday 3 (Mon=0)
        if days_ahead <= 0:
            days_ahead += 7
        next_thursday = now + pd.Timedelta(days=days_ahead)
        return next_thursday.strftime("%d-%b-%Y").upper()

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def _size_positions(self, is_small_size: bool) -> int:
        """
        Return recommended lot count.

        In high_volatility regimes only 1 lot is traded regardless of
        max_lots setting to cap risk in uncertain conditions.

        Parameters
        ----------
        is_small_size : bool — True for high-volatility signals

        Returns
        -------
        int — number of lots (≥ 1)
        """
        if is_small_size:
            return 1
        return max(1, self.max_lots)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _latest_close(df: pd.DataFrame) -> float:
    """Return the most recent close price from an OHLCV DataFrame."""
    if df is None or df.empty or "close" not in df.columns:
        return 0.0
    return float(df["close"].iloc[-1])


def _round_to_strike(price: float, step: int = 50) -> int:
    """Round a spot price to the nearest valid Nifty strike."""
    return int(round(price / step) * step)


def _dir_label(direction: int) -> str:
    mapping = {1: "UP", -1: "DOWN", 0: "FLAT"}
    return mapping.get(direction, str(direction))
