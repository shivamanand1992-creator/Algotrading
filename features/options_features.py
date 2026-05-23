"""
Options Feature Engine for Nifty50 Intraday Options AI Trading System.

Computes options-specific features from PCR, Open Interest, Implied Volatility,
Max Pain, and options premium data.  Also provides a pure-numpy Black-Scholes
greek approximation that requires no external options pricing library.

All methods accept and return pandas DataFrames; computation is vectorised.
"""

from __future__ import annotations

import math
import warnings
from typing import Literal

import numpy as np
import pandas as pd
from loguru import logger

warnings.filterwarnings("ignore", category=RuntimeWarning)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _require_columns(df: pd.DataFrame, cols: list[str], caller: str) -> None:
    """Raise an informative ValueError when required columns are absent."""
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"[{caller}] Missing columns: {missing}. Available: {list(df.columns)}"
        )


def _safe_divide(
    a: pd.Series | np.ndarray,
    b: pd.Series | np.ndarray,
    fill: float = np.nan,
) -> pd.Series | np.ndarray:
    """Element-wise division, replacing division-by-zero with *fill*."""
    if isinstance(a, pd.Series) and isinstance(b, pd.Series):
        return (a / b.replace(0, np.nan)).fillna(fill)
    # numpy path
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(b == 0, fill, a / np.where(b == 0, 1, b))
    return result


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    """
    Cumulative distribution function of the standard normal distribution.

    Pure numpy implementation using the math.erf approach vectorised with
    scipy.special.erf when available, otherwise falls back to a fast
    polynomial approximation (Abramowitz & Stegun 26.2.17, max error < 7.5e-8).
    """
    try:
        from scipy.special import erf as _erf  # preferred path
        return 0.5 * (1.0 + _erf(x / math.sqrt(2.0)))
    except ImportError:
        # Polynomial approximation — adequate for greek calculations
        sign = np.sign(x)
        ax = np.abs(x) / math.sqrt(2.0)
        t = 1.0 / (1.0 + 0.3275911 * ax)
        poly = (
            0.254829592 * t
            - 0.284496736 * t ** 2
            + 1.421413741 * t ** 3
            - 1.453152027 * t ** 4
            + 1.061405429 * t ** 5
        )
        approx = 1.0 - poly * np.exp(-(ax ** 2))
        return 0.5 * (1.0 + sign * approx)


def _norm_pdf(x: np.ndarray) -> np.ndarray:
    """Probability density function of the standard normal distribution."""
    return np.exp(-0.5 * x ** 2) / math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------------------
# Options Feature Engine
# ---------------------------------------------------------------------------

class OptionsFeatureEngine:
    """
    Computes options-specific features for the Nifty50 AI trading system.

    All ``add_*`` methods accept a base OHLCV DataFrame and supplementary
    options data Series/scalars, then return an enriched copy.

    Usage
    -----
    >>> engine = OptionsFeatureEngine()
    >>> df = engine.add_pcr_features(df, pcr_series)
    >>> df = engine.add_oi_features(df, ce_oi_series, pe_oi_series)
    >>> df = engine.add_iv_features(df, iv_series)
    >>> df = engine.add_max_pain_feature(df, max_pain=18300, spot=18410)
    >>> df = engine.add_options_momentum(df)
    """

    # ------------------------------------------------------------------
    # PCR Features
    # ------------------------------------------------------------------

    def add_pcr_features(
        self,
        df: pd.DataFrame,
        pcr_series: pd.Series,
    ) -> pd.DataFrame:
        """
        Put-Call Ratio features.

        Parameters
        ----------
        df         : base DataFrame (must be index-aligned with pcr_series)
        pcr_series : PCR computed as PE_OI / CE_OI (same index as df)

        Adds columns
        ------------
        pcr              — raw PCR value
        pcr_ma5          — 5-period simple moving average of PCR
        pcr_signal       — +1 (bullish/contrarian-put-heavy),
                           -1 (bearish/contrarian-call-heavy),
                            0 (neutral)
                           Thresholds: PCR > 1.2 → bullish (+1),
                                       PCR < 0.7 → bearish (-1)
        pcr_zscore       — z-score of PCR vs 20-period rolling mean/std
        pcr_trend        — 1 if pcr > pcr_ma5 (puts increasing), -1 otherwise
        """
        df = df.copy()

        # Align PCR to df's index; fill missing with forward-fill then NaN
        pcr = pcr_series.reindex(df.index).ffill()

        df["pcr"] = pcr
        df["pcr_ma5"] = pcr.rolling(window=5, min_periods=1).mean()

        # Signal (contrarian interpretation standard in Indian markets)
        df["pcr_signal"] = np.where(
            pcr > 1.2, 1,
            np.where(pcr < 0.7, -1, 0),
        )

        # Z-score: how stretched PCR is relative to recent history
        pcr_roll_mean = pcr.rolling(window=20, min_periods=5).mean()
        pcr_roll_std = pcr.rolling(window=20, min_periods=5).std()
        df["pcr_zscore"] = _safe_divide(
            pcr - pcr_roll_mean, pcr_roll_std.replace(0, np.nan)
        )

        # Trend direction of PCR itself
        df["pcr_trend"] = np.where(pcr > df["pcr_ma5"], 1, -1)

        logger.debug("PCR features added.")
        return df

    # ------------------------------------------------------------------
    # Open Interest Features
    # ------------------------------------------------------------------

    def add_oi_features(
        self,
        df: pd.DataFrame,
        ce_oi: pd.Series,
        pe_oi: pd.Series,
    ) -> pd.DataFrame:
        """
        Open Interest features including OI change % and buildup signals.

        Parameters
        ----------
        df    : base DataFrame (index-aligned)
        ce_oi : CE (Call) open interest series (same index as df)
        pe_oi : PE (Put)  open interest series (same index as df)

        Buildup classification per bar
        --------------------------------
        long_buildup   : price up  + OI up   → fresh long positions entering
        short_buildup  : price down + OI up   → fresh short positions entering
        long_unwinding : price down + OI down → longs exiting
        short_covering : price up  + OI down  → shorts covering

        Adds columns
        ------------
        ce_oi, pe_oi         — raw OI values
        total_oi             — CE + PE OI
        oi_ratio             — CE OI / PE OI
        ce_oi_chg_pct        — % change in CE OI bar-over-bar
        pe_oi_chg_pct        — % change in PE OI bar-over-bar
        total_oi_chg_pct     — % change in total OI bar-over-bar
        oi_buildup           — integer signal: 1=long_buildup, -1=short_buildup,
                               2=long_unwinding, -2=short_covering, 0=neutral
        oi_buildup_label     — human-readable string version of oi_buildup
        oi_concentration     — max OI at any single strike / total (external
                               concentration; here approximated as max(ce,pe)/total)
        """
        _require_columns(df, ["close"], "add_oi_features")
        df = df.copy()

        ce = ce_oi.reindex(df.index).ffill()
        pe = pe_oi.reindex(df.index).ffill()

        df["ce_oi"] = ce
        df["pe_oi"] = pe
        df["total_oi"] = ce + pe

        # OI ratio (CE vs PE balance)
        df["oi_ratio"] = _safe_divide(ce, pe.replace(0, np.nan))

        # Bar-over-bar percentage change
        df["ce_oi_chg_pct"] = ce.pct_change() * 100.0
        df["pe_oi_chg_pct"] = pe.pct_change() * 100.0
        df["total_oi_chg_pct"] = df["total_oi"].pct_change() * 100.0

        # Price direction this bar
        price_up = df["close"].diff() > 0
        price_down = df["close"].diff() < 0
        oi_up = df["total_oi"].diff() > 0
        oi_down = df["total_oi"].diff() < 0

        # Encode buildup signal as integer
        buildup = np.where(
            price_up & oi_up, 1,          # long buildup
            np.where(
                price_down & oi_up, -1,    # short buildup
                np.where(
                    price_down & oi_down, 2,   # long unwinding
                    np.where(
                        price_up & oi_down, -2, # short covering
                        0,                       # neutral / ambiguous
                    ),
                ),
            ),
        )
        df["oi_buildup"] = buildup

        _label_map = {
            1: "long_buildup",
            -1: "short_buildup",
            2: "long_unwinding",
            -2: "short_covering",
            0: "neutral",
        }
        df["oi_buildup_label"] = df["oi_buildup"].map(_label_map)

        # Concentration: how skewed is the CE/PE split?
        df["oi_concentration"] = _safe_divide(
            pd.concat([ce, pe], axis=1).max(axis=1),
            df["total_oi"].replace(0, np.nan),
        )

        logger.debug("OI features added.")
        return df

    # ------------------------------------------------------------------
    # IV Features
    # ------------------------------------------------------------------

    def add_iv_features(
        self,
        df: pd.DataFrame,
        iv_series: pd.Series,
        percentile_window: int = 252,
    ) -> pd.DataFrame:
        """
        Implied Volatility features.

        Parameters
        ----------
        df              : base DataFrame
        iv_series       : IV series (annualised %, same index as df)
        percentile_window : rolling window for IV percentile (default 252 bars ≈ 1 year)

        Adds columns
        ------------
        iv               — raw IV value
        iv_ma5           — 5-bar MA of IV
        iv_ma20          — 20-bar MA of IV
        iv_change        — bar-over-bar absolute change in IV
        iv_change_pct    — bar-over-bar % change in IV
        iv_percentile    — rolling percentile rank (0–100) over *percentile_window*
        iv_zscore        — z-score vs 20-bar mean/std
        iv_regime        — 0=low (<30th pct), 1=normal (30–70th), 2=high (>70th)
        iv_term_slope    — placeholder: same as iv_change (term structure slope
                           needs multi-expiry data; replaced by rolling diff)
        """
        df = df.copy()

        iv = iv_series.reindex(df.index).ffill()

        df["iv"] = iv
        df["iv_ma5"] = iv.rolling(window=5, min_periods=1).mean()
        df["iv_ma20"] = iv.rolling(window=20, min_periods=1).mean()
        df["iv_change"] = iv.diff()
        df["iv_change_pct"] = iv.pct_change() * 100.0

        # Rolling percentile rank
        def _pct_rank(series: pd.Series, window: int) -> pd.Series:
            """Vectorised rolling percentile rank using expanding up to *window*."""
            def _rank_last(arr: np.ndarray) -> float:
                val = arr[-1]
                below = np.sum(arr < val)
                return (below / (len(arr) - 1)) * 100.0 if len(arr) > 1 else 50.0

            return series.rolling(window=window, min_periods=10).apply(
                _rank_last, raw=True
            )

        df["iv_percentile"] = _pct_rank(iv, percentile_window)

        # Z-score
        iv_roll_mean = iv.rolling(window=20, min_periods=5).mean()
        iv_roll_std = iv.rolling(window=20, min_periods=5).std()
        df["iv_zscore"] = _safe_divide(
            iv - iv_roll_mean, iv_roll_std.replace(0, np.nan)
        )

        # IV regime classification
        df["iv_regime"] = np.where(
            df["iv_percentile"] < 30, 0,    # low vol
            np.where(df["iv_percentile"] > 70, 2, 1),  # high / normal
        )

        # Term slope proxy: rolling 5-bar change in IV (accelerating vs decelerating)
        df["iv_term_slope"] = iv.diff(5)

        logger.debug("IV features added.")
        return df

    # ------------------------------------------------------------------
    # Max Pain Feature
    # ------------------------------------------------------------------

    def add_max_pain_feature(
        self,
        df: pd.DataFrame,
        max_pain: float | pd.Series,
        spot: float | pd.Series,
    ) -> pd.DataFrame:
        """
        Distance of the current spot price from options max pain level.

        Max pain is the strike price at which option buyers suffer the most
        loss at expiry.  Price tends to gravitate towards max pain as expiry
        approaches (max pain theory).

        Parameters
        ----------
        df        : base DataFrame
        max_pain  : scalar or Series — max pain strike price
        spot      : scalar or Series — current Nifty spot price

        Adds columns
        ------------
        max_pain             — max pain strike
        max_pain_dist_pct    — (spot - max_pain) / max_pain * 100
                               Positive → spot above max pain (CE sellers favoured)
                               Negative → spot below max pain (PE sellers favoured)
        max_pain_abs_dist    — |spot - max_pain| / max_pain * 100
        max_pain_gravity     — 1 / (1 + max_pain_abs_dist) — how strongly price
                               is being pulled toward max pain (0→far, 1→at pain)
        """
        df = df.copy()

        if isinstance(max_pain, (int, float, np.integer, np.floating)):
            mp = pd.Series(max_pain, index=df.index, dtype=float)
        elif isinstance(max_pain, np.ndarray):
            mp = pd.Series(max_pain, index=df.index, dtype=float)
        else:
            mp = max_pain.reindex(df.index).ffill()

        if isinstance(spot, (int, float, np.integer, np.floating)):
            sp = pd.Series(spot, index=df.index, dtype=float)
        elif isinstance(spot, np.ndarray):
            sp = pd.Series(spot, index=df.index, dtype=float)
        else:
            sp = spot.reindex(df.index).ffill()

        df["max_pain"] = mp
        df["max_pain_dist_pct"] = _safe_divide(sp - mp, mp.replace(0, np.nan)) * 100.0
        df["max_pain_abs_dist"] = df["max_pain_dist_pct"].abs()
        df["max_pain_gravity"] = 1.0 / (1.0 + df["max_pain_abs_dist"])

        logger.debug("Max pain features added.")
        return df

    # ------------------------------------------------------------------
    # Options Momentum
    # ------------------------------------------------------------------

    def add_options_momentum(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Momentum features derived from options premium changes.

        Requires that the DataFrame already contains ``close`` (underlying or
        option LTP) and optionally ``ce_oi`` / ``pe_oi`` columns (added by
        ``add_oi_features``).

        Adds columns
        ------------
        premium_return_1   — 1-bar % change in premium (close)
        premium_return_5   — 5-bar % change in premium
        premium_momentum   — sign of 3-bar EMA of premium_return_1
        premium_vol_10     — rolling 10-bar realised vol of log returns
        premium_accel      — premium_return_1 - premium_return_1.shift(1)
                             (rate of change of momentum)
        options_flow_score — composite score:
                               +1 (bullish):  premium rising + OI rising on PE
                               -1 (bearish):  premium rising + OI rising on CE
                                0 (neutral):  otherwise
                             (only populated when ce_oi/pe_oi columns present)
        """
        _require_columns(df, ["close"], "add_options_momentum")
        df = df.copy()

        log_ret = np.log(df["close"] / df["close"].shift(1))

        df["premium_return_1"] = df["close"].pct_change(1) * 100.0
        df["premium_return_5"] = df["close"].pct_change(5) * 100.0
        df["premium_momentum"] = np.sign(
            df["premium_return_1"].ewm(span=3, adjust=False).mean()
        )
        df["premium_vol_10"] = log_ret.rolling(10).std() * 100.0
        df["premium_accel"] = df["premium_return_1"].diff()

        # Composite flow score (requires OI data from add_oi_features)
        if "pe_oi_chg_pct" in df.columns and "ce_oi_chg_pct" in df.columns:
            price_up = df["premium_return_1"] > 0
            price_down = df["premium_return_1"] < 0
            pe_rising = df["pe_oi_chg_pct"] > 0
            ce_rising = df["ce_oi_chg_pct"] > 0

            df["options_flow_score"] = np.where(
                price_up & pe_rising, 1,
                np.where(price_down & ce_rising, -1, 0),
            )
        else:
            df["options_flow_score"] = np.nan

        logger.debug("Options momentum features added.")
        return df

    # ------------------------------------------------------------------
    # Black-Scholes Greeks (pure numpy, no external library)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_greeks_approximation(
        S: float | np.ndarray,
        K: float | np.ndarray,
        T: float | np.ndarray,
        r: float | np.ndarray,
        sigma: float | np.ndarray,
        option_type: Literal["CE", "PE", "call", "put"] = "CE",
    ) -> dict[str, float | np.ndarray]:
        """
        Compute Black-Scholes option greeks using pure numpy arithmetic.

        No external options pricing library (mibian, py_vollib, etc.) is required.

        Parameters
        ----------
        S           : Spot / underlying price (e.g. 18450.0)
        K           : Strike price            (e.g. 18400.0)
        T           : Time to expiry in *years* (e.g. 7/365 for 7 calendar days)
        r           : Risk-free rate as decimal  (e.g. 0.065 for 6.5%)
        sigma       : Implied volatility as decimal (e.g. 0.15 for 15% IV)
        option_type : "CE" / "call" for call, "PE" / "put" for put

        Returns
        -------
        dict with keys:
            delta : rate of change of option price w.r.t. underlying
            gamma : rate of change of delta w.r.t. underlying
            theta : daily time decay (in option price units, divided by 365)
            vega  : sensitivity to 1-point change in IV (sigma * 0.01 shock)
            rho   : sensitivity to 1% change in risk-free rate
            d1    : BS d1 intermediate value
            d2    : BS d2 intermediate value
            option_price : theoretical BS price

        Notes
        -----
        When T ≤ 0 all greeks are set to intrinsic-value / 0 equivalents.
        Accepts scalars or numpy arrays for batch computation.
        """
        # Convert inputs to numpy arrays for uniform treatment
        S = np.asarray(S, dtype=float)
        K = np.asarray(K, dtype=float)
        T = np.asarray(T, dtype=float)
        r = np.asarray(r, dtype=float)
        sigma = np.asarray(sigma, dtype=float)

        scalar_input = (S.ndim == 0)
        S = np.atleast_1d(S)
        K = np.atleast_1d(K)
        T = np.atleast_1d(T)
        r = np.atleast_1d(r)
        sigma = np.atleast_1d(sigma)

        is_call = option_type.upper() in ("CE", "CALL")

        # Mask for expired / zero-time options
        valid = (T > 1e-6) & (sigma > 1e-6) & (S > 0) & (K > 0)

        # Pre-allocate output arrays
        shape = np.broadcast_shapes(S.shape, K.shape, T.shape, r.shape, sigma.shape)
        delta_arr = np.zeros(shape)
        gamma_arr = np.zeros(shape)
        theta_arr = np.zeros(shape)
        vega_arr = np.zeros(shape)
        rho_arr = np.zeros(shape)
        d1_arr = np.full(shape, np.nan)
        d2_arr = np.full(shape, np.nan)
        price_arr = np.zeros(shape)

        # Broadcast all arrays to common shape
        S_ = np.broadcast_to(S, shape).copy()
        K_ = np.broadcast_to(K, shape).copy()
        T_ = np.broadcast_to(T, shape).copy()
        r_ = np.broadcast_to(r, shape).copy()
        sigma_ = np.broadcast_to(sigma, shape).copy()
        valid_ = np.broadcast_to(valid, shape).copy()

        if np.any(valid_):
            sv = S_[valid_]
            kv = K_[valid_]
            tv = T_[valid_]
            rv = r_[valid_]
            sigv = sigma_[valid_]

            sqrt_t = np.sqrt(tv)
            d1 = (np.log(sv / kv) + (rv + 0.5 * sigv ** 2) * tv) / (sigv * sqrt_t)
            d2 = d1 - sigv * sqrt_t

            nd1 = _norm_cdf(d1)
            nd2 = _norm_cdf(d2)
            n_neg_d1 = _norm_cdf(-d1)
            n_neg_d2 = _norm_cdf(-d2)
            pdf_d1 = _norm_pdf(d1)

            disc = np.exp(-rv * tv)

            if is_call:
                price_v = sv * nd1 - kv * disc * nd2
                delta_v = nd1
                rho_v = kv * tv * disc * nd2 / 100.0
            else:
                price_v = kv * disc * n_neg_d2 - sv * n_neg_d1
                delta_v = nd1 - 1.0          # negative for puts
                rho_v = -kv * tv * disc * n_neg_d2 / 100.0

            gamma_v = pdf_d1 / (sv * sigv * sqrt_t)
            vega_v = sv * pdf_d1 * sqrt_t / 100.0   # per 1% IV change

            # Theta: daily decay (annualised theta / 365)
            if is_call:
                theta_v = (
                    -(sv * pdf_d1 * sigv) / (2.0 * sqrt_t)
                    - rv * kv * disc * nd2
                ) / 365.0
            else:
                theta_v = (
                    -(sv * pdf_d1 * sigv) / (2.0 * sqrt_t)
                    + rv * kv * disc * n_neg_d2
                ) / 365.0

            d1_arr[valid_] = d1
            d2_arr[valid_] = d2
            delta_arr[valid_] = delta_v
            gamma_arr[valid_] = gamma_v
            theta_arr[valid_] = theta_v
            vega_arr[valid_] = vega_v
            rho_arr[valid_] = rho_v
            price_arr[valid_] = price_v

        # For expired options: intrinsic value only, greeks → 0
        expired = ~valid_
        if np.any(expired):
            if is_call:
                price_arr[expired] = np.maximum(S_[expired] - K_[expired], 0.0)
            else:
                price_arr[expired] = np.maximum(K_[expired] - S_[expired], 0.0)

        # Return scalars if scalar inputs were provided
        def _maybe_scalar(arr: np.ndarray) -> float | np.ndarray:
            return float(arr[0]) if scalar_input else arr

        return {
            "delta": _maybe_scalar(delta_arr),
            "gamma": _maybe_scalar(gamma_arr),
            "theta": _maybe_scalar(theta_arr),
            "vega": _maybe_scalar(vega_arr),
            "rho": _maybe_scalar(rho_arr),
            "d1": _maybe_scalar(d1_arr),
            "d2": _maybe_scalar(d2_arr),
            "option_price": _maybe_scalar(price_arr),
        }

    # ------------------------------------------------------------------
    # Convenience: add greeks for a whole DataFrame of options data
    # ------------------------------------------------------------------

    def add_greeks_to_df(
        self,
        df: pd.DataFrame,
        spot_col: str = "close",
        strike_col: str = "strike",
        tte_col: str = "tte_years",
        iv_col: str = "iv",
        rate: float = 0.065,
        option_type: Literal["CE", "PE"] = "CE",
    ) -> pd.DataFrame:
        """
        Vectorised greek computation across all rows of *df*.

        Parameters
        ----------
        df          : DataFrame containing options data
        spot_col    : column name for underlying price
        strike_col  : column name for strike price
        tte_col     : column name for time-to-expiry (in years)
        iv_col      : column name for implied volatility (as decimal, e.g. 0.15)
        rate        : risk-free rate (scalar, default 6.5%)
        option_type : "CE" or "PE"

        Adds columns: bs_delta, bs_gamma, bs_theta, bs_vega, bs_rho, bs_price
        """
        required = [spot_col, strike_col, tte_col, iv_col]
        _require_columns(df, required, "add_greeks_to_df")
        df = df.copy()

        greeks = self.compute_greeks_approximation(
            S=df[spot_col].values,
            K=df[strike_col].values,
            T=df[tte_col].values,
            r=np.full(len(df), rate),
            sigma=df[iv_col].values,
            option_type=option_type,
        )

        df["bs_delta"] = greeks["delta"]
        df["bs_gamma"] = greeks["gamma"]
        df["bs_theta"] = greeks["theta"]
        df["bs_vega"] = greeks["vega"]
        df["bs_rho"] = greeks["rho"]
        df["bs_price"] = greeks["option_price"]

        logger.debug(f"BS greeks added ({option_type}) for {len(df)} rows.")
        return df
