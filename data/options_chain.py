"""
Options chain analysis and utilities for Nifty50 intraday options trading.

Provides OptionsChainAnalyzer with helpers for:
  - ATM strike and surrounding strike selection
  - Put-Call Ratio (PCR) by open interest
  - Max-pain calculation
  - IV rank / percentile
  - Angel One symbol token lookup
  - Nifty weekly expiry-date enumeration
  - Clean DataFrame builder from raw chain data
"""

import os
import math
import json
import yaml
import time
import pytz
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np
from loguru import logger
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Module bootstrap
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

_IST = pytz.timezone("Asia/Kolkata")

# Nifty strike interval in points
_DEFAULT_STRIKE_INTERVAL = 50

# Weekday index for Thursday (Monday=0 … Sunday=6)
_THURSDAY = 3


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _to_float(value, default: float = 0.0) -> float:
    """Safe float conversion."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default: int = 0) -> int:
    """Safe int conversion."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class OptionsChainAnalyzer:
    """
    Utility class for options chain analysis on Nifty50.

    All methods are stateless (class methods or static methods) unless they
    rely on the symbol-token map loaded at construction time.

    Parameters
    ----------
    symbol_token_map : dict, optional
        Pre-loaded mapping of ``{(strike, option_type, expiry): token}`` or
        a raw instrument-list dict from the Angel One instruments endpoint.
        If omitted, ``parse_option_symbol()`` will raise ValueError.
    """

    def __init__(self, symbol_token_map: Optional[Dict] = None) -> None:
        self._symbol_token_map: Dict = symbol_token_map or {}
        logger.info(
            "OptionsChainAnalyzer initialised "
            f"(symbol_token_map entries: {len(self._symbol_token_map)})."
        )

    # ------------------------------------------------------------------
    # Strike selection
    # ------------------------------------------------------------------

    @staticmethod
    def get_atm_strike(
        spot_price: float,
        strike_interval: int = _DEFAULT_STRIKE_INTERVAL,
    ) -> int:
        """
        Round ``spot_price`` to the nearest multiple of ``strike_interval``.

        Follows standard rounding: 0.5 rounds up.

        Parameters
        ----------
        spot_price       : float   current Nifty spot index value
        strike_interval  : int     strike gap in points (default 50 for Nifty)

        Returns
        -------
        int  ATM strike price

        Examples
        --------
        >>> OptionsChainAnalyzer.get_atm_strike(22374.0)
        22350
        >>> OptionsChainAnalyzer.get_atm_strike(22376.0)
        22400
        """
        if strike_interval <= 0:
            raise ValueError("strike_interval must be positive.")
        atm = round(spot_price / strike_interval) * strike_interval
        logger.debug(f"ATM strike for spot {spot_price}: {atm}")
        return int(atm)

    @staticmethod
    def get_strikes_around_atm(
        spot_price: float,
        n_strikes: int = 5,
        strike_interval: int = _DEFAULT_STRIKE_INTERVAL,
    ) -> List[int]:
        """
        Return a sorted list of strikes centred on ATM.

        The result contains ``2 * n_strikes + 1`` strikes:
        ``n_strikes`` below ATM, ATM itself, and ``n_strikes`` above ATM.

        Parameters
        ----------
        spot_price      : float  Nifty spot
        n_strikes       : int    number of strikes on each side of ATM
        strike_interval : int    strike gap in points

        Returns
        -------
        list[int]  sorted strike prices, e.g. [22200, 22250, …, 22700]
        """
        if n_strikes < 0:
            raise ValueError("n_strikes must be non-negative.")
        atm = OptionsChainAnalyzer.get_atm_strike(spot_price, strike_interval)
        strikes = [
            int(atm + i * strike_interval)
            for i in range(-n_strikes, n_strikes + 1)
        ]
        logger.debug(
            f"Strikes around ATM {atm} (n={n_strikes}): "
            f"{strikes[0]}…{strikes[-1]}"
        )
        return strikes

    # ------------------------------------------------------------------
    # PCR and max pain
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_pcr(chain_data: pd.DataFrame) -> float:
        """
        Compute the Put-Call Ratio by total open interest.

        PCR = sum(PE OI) / sum(CE OI)

        A PCR > 1 is broadly bullish (more put writing); < 1 is bearish.

        Parameters
        ----------
        chain_data : pd.DataFrame
            Must contain columns ``ce_oi`` and ``pe_oi`` (numeric).

        Returns
        -------
        float  PCR value; returns 0.0 if CE OI is zero.
        """
        required = {"ce_oi", "pe_oi"}
        missing = required - set(chain_data.columns)
        if missing:
            raise ValueError(f"chain_data missing columns: {missing}")

        total_ce_oi = chain_data["ce_oi"].fillna(0).sum()
        total_pe_oi = chain_data["pe_oi"].fillna(0).sum()

        if total_ce_oi == 0:
            logger.warning("Total CE OI is zero; PCR is undefined, returning 0.0.")
            return 0.0

        pcr = total_pe_oi / total_ce_oi
        logger.debug(
            f"PCR = {pcr:.4f} (PE OI={total_pe_oi:,}, CE OI={total_ce_oi:,})"
        )
        return round(float(pcr), 4)

    @staticmethod
    def calculate_max_pain(chain_data: pd.DataFrame) -> int:
        """
        Find the max-pain strike: the price at which aggregate option seller
        losses are minimised (i.e. aggregate buyer pain is maximised).

        Algorithm
        ---------
        For each candidate strike K_i in the chain:
            pain_i = Σ_j [ CE_OI_j × max(0, K_j - K_i) ]
                   + Σ_j [ PE_OI_j × max(0, K_i - K_j) ]
        Max-pain strike = argmin(pain_i)

        Parameters
        ----------
        chain_data : pd.DataFrame
            Must contain columns: ``strike``, ``ce_oi``, ``pe_oi``.

        Returns
        -------
        int  max-pain strike price
        """
        required = {"strike", "ce_oi", "pe_oi"}
        missing = required - set(chain_data.columns)
        if missing:
            raise ValueError(f"chain_data missing columns: {missing}")

        df = chain_data[["strike", "ce_oi", "pe_oi"]].copy()
        df["ce_oi"] = df["ce_oi"].fillna(0)
        df["pe_oi"] = df["pe_oi"].fillna(0)
        strikes = df["strike"].values.astype(float)

        min_pain = float("inf")
        max_pain_strike = int(strikes[0])

        for candidate in strikes:
            ce_pain = float(
                (df["ce_oi"] * np.maximum(0.0, df["strike"] - candidate)).sum()
            )
            pe_pain = float(
                (df["pe_oi"] * np.maximum(0.0, candidate - df["strike"])).sum()
            )
            total_pain = ce_pain + pe_pain
            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_strike = int(candidate)

        logger.debug(
            f"Max-pain strike: {max_pain_strike} (total pain={min_pain:,.0f})"
        )
        return max_pain_strike

    # ------------------------------------------------------------------
    # IV analytics
    # ------------------------------------------------------------------

    @staticmethod
    def get_iv_percentile(
        symbol: str,
        current_iv: float,
        historical_ivs: List[float],
    ) -> Tuple[float, float]:
        """
        Compute IV Rank and IV Percentile for a symbol.

        IV Rank      = (current_iv - 52w_low) / (52w_high - 52w_low) × 100
        IV Percentile = % of historical readings below current_iv

        Parameters
        ----------
        symbol        : str           instrument name (for logging)
        current_iv    : float         today's implied volatility (e.g. 14.5 for 14.5%)
        historical_ivs: list[float]   historical IV readings (at least 2 required)

        Returns
        -------
        (iv_rank, iv_percentile) : (float, float)
            Both values are in [0, 100].

        Raises
        ------
        ValueError  if historical_ivs has fewer than 2 elements
        """
        if len(historical_ivs) < 2:
            raise ValueError(
                f"historical_ivs must contain at least 2 readings; "
                f"got {len(historical_ivs)}."
            )

        iv_min = min(historical_ivs)
        iv_max = max(historical_ivs)

        if iv_max == iv_min:
            logger.warning(
                f"[{symbol}] All historical IVs identical ({iv_min}); "
                "rank/percentile are 0.0."
            )
            return 0.0, 0.0

        iv_rank = ((current_iv - iv_min) / (iv_max - iv_min)) * 100.0
        iv_rank = round(max(0.0, min(100.0, iv_rank)), 2)

        below = sum(1 for iv in historical_ivs if iv < current_iv)
        iv_percentile = round((below / len(historical_ivs)) * 100.0, 2)

        logger.debug(
            f"[{symbol}] current_iv={current_iv:.2f}% "
            f"IV_Rank={iv_rank:.1f}% IV_Percentile={iv_percentile:.1f}%"
        )
        return iv_rank, iv_percentile

    # ------------------------------------------------------------------
    # Symbol / token lookup
    # ------------------------------------------------------------------

    def parse_option_symbol(
        self,
        strike: int,
        option_type: str,
        expiry: str,
        underlying: str = "NIFTY",
    ) -> Dict[str, str]:
        """
        Look up the Angel One trading symbol and instrument token for a
        specific option contract.

        The method searches ``self._symbol_token_map``, which should be
        loaded from the Angel One instruments CSV/JSON file.

        Parameters
        ----------
        strike      : int   option strike price, e.g. 22400
        option_type : str   "CE" or "PE"
        expiry      : str   expiry in "DDMMMYYYY" or "DD-MMM-YYYY" format
                            e.g. "25MAY2023" or "25-MAY-2023"
        underlying  : str   "NIFTY" (default)

        Returns
        -------
        dict  {"symbol": str, "token": str, "exchange": str}

        Raises
        ------
        ValueError  if the contract is not found in the map.
        """
        option_type = option_type.upper().strip()
        if option_type not in ("CE", "PE"):
            raise ValueError(f"option_type must be 'CE' or 'PE'; got '{option_type}'")

        # Normalise expiry to "DDMMMYYYY" (no dashes)
        expiry_clean = expiry.replace("-", "").upper()

        # Construct the standard Angel One trading symbol
        # Format: NIFTY<DDMMMYYYY><STRIKE><CE|PE>  e.g. NIFTY25MAY202322400CE
        trading_symbol = f"{underlying.upper()}{expiry_clean}{strike}{option_type}"

        logger.debug(f"Looking up symbol token for '{trading_symbol}'.")

        # Direct lookup by constructed symbol
        entry = self._symbol_token_map.get(trading_symbol)
        if entry is not None:
            if isinstance(entry, dict):
                return {
                    "symbol":   trading_symbol,
                    "token":    str(entry.get("token", entry.get("symboltoken", ""))),
                    "exchange": str(entry.get("exchange", "NFO")),
                }
            return {
                "symbol":   trading_symbol,
                "token":    str(entry),
                "exchange": "NFO",
            }

        # Fallback: scan map for entries that match key components
        for key, val in self._symbol_token_map.items():
            key_str = str(key).upper()
            if (
                underlying.upper() in key_str
                and str(strike) in key_str
                and option_type in key_str
                and expiry_clean in key_str
            ):
                token = (
                    str(val.get("token", val.get("symboltoken", val)))
                    if isinstance(val, dict)
                    else str(val)
                )
                exchange = (
                    str(val.get("exchange", "NFO")) if isinstance(val, dict) else "NFO"
                )
                logger.debug(f"Found via scan: key={key}, token={token}")
                return {"symbol": key_str, "token": token, "exchange": exchange}

        raise ValueError(
            f"Token not found for {underlying} {strike} {option_type} exp={expiry}. "
            "Ensure symbol_token_map is populated with the current instruments list."
        )

    # ------------------------------------------------------------------
    # Expiry date utilities
    # ------------------------------------------------------------------

    @staticmethod
    def get_expiry_dates(
        n_weeks: int = 8,
        reference_date: Optional[date] = None,
    ) -> List[date]:
        """
        Return the next ``n_weeks`` Nifty weekly expiry dates (Thursdays).

        If a Thursday is a market holiday the exchange typically moves
        expiry to Wednesday; this method does NOT account for holidays —
        call your broker's holiday API and filter the list if needed.

        Parameters
        ----------
        n_weeks        : int          number of upcoming expiries to return
        reference_date : date, optional  start from this date (default: today IST)

        Returns
        -------
        list[date]  sorted list of upcoming Thursday dates
        """
        if reference_date is None:
            reference_date = datetime.now(_IST).date()

        # Find the next Thursday on or after reference_date
        days_ahead = (_THURSDAY - reference_date.weekday()) % 7
        first_thursday = reference_date + timedelta(days=days_ahead)

        expiries = [
            first_thursday + timedelta(weeks=i)
            for i in range(n_weeks)
        ]
        logger.debug(
            f"Next {n_weeks} expiry dates: "
            f"{[d.strftime('%d-%b-%Y') for d in expiries]}"
        )
        return expiries

    @staticmethod
    def get_nearest_expiry(reference_date: Optional[date] = None) -> date:
        """
        Return the closest upcoming Nifty weekly expiry (Thursday).

        If today IS Thursday and the session has not yet expired, today is
        returned. Otherwise the next Thursday is returned.

        Parameters
        ----------
        reference_date : date, optional  (default: today IST)

        Returns
        -------
        date  nearest expiry date
        """
        if reference_date is None:
            reference_date = datetime.now(_IST).date()

        days_ahead = (_THURSDAY - reference_date.weekday()) % 7
        nearest = reference_date + timedelta(days=days_ahead)
        logger.debug(
            f"Nearest expiry for {reference_date}: {nearest.strftime('%d-%b-%Y')}"
        )
        return nearest

    @staticmethod
    def format_expiry_angel(expiry_date: date) -> str:
        """
        Format a date as the string Angel One API expects for expiry.

        Returns ``"DD-MMM-YYYY"`` in uppercase, e.g. ``"25-MAY-2023"``.

        Parameters
        ----------
        expiry_date : date

        Returns
        -------
        str
        """
        return expiry_date.strftime("%d-%b-%Y").upper()

    # ------------------------------------------------------------------
    # DataFrame builder
    # ------------------------------------------------------------------

    @staticmethod
    def build_option_chain_df(raw_chain_data: Dict) -> pd.DataFrame:
        """
        Build a clean, analysis-ready options chain DataFrame from the raw
        Angel One API response returned by ``AngelOneClient.get_option_chain()``.

        The function handles two common response shapes:
          1. ``{"fetched": [{"strikePrice": ..., "CE": {...}, "PE": {...}}, ...]}``.
          2. A flat list of instrument dicts with ``optiontype`` keys.

        Output columns
        --------------
        strike        : int    strike price
        ce_oi         : int    call open interest
        ce_oi_change  : int    change in call OI since previous close
        ce_iv         : float  call implied volatility (%)
        ce_ltp        : float  call last traded price
        ce_volume     : int    call traded volume today
        pe_oi         : int    put open interest
        pe_oi_change  : int    change in put OI since previous close
        pe_iv         : float  put implied volatility (%)
        pe_ltp        : float  put last traded price
        pe_volume     : int    put traded volume today
        total_oi      : int    ce_oi + pe_oi

        Parameters
        ----------
        raw_chain_data : dict
            Returned by ``AngelOneClient.get_option_chain()``.

        Returns
        -------
        pd.DataFrame  sorted ascending by strike; one row per strike.
        """
        if not raw_chain_data:
            logger.warning("build_option_chain_df: empty raw_chain_data received.")
            return _empty_chain_df()

        rows: List[Dict] = []

        # ---- Shape 1: {"fetched": [...]} ----
        fetched = raw_chain_data.get("fetched", None)
        if fetched is not None and isinstance(fetched, list):
            logger.debug(
                f"build_option_chain_df: processing {len(fetched)} fetched records."
            )
            for record in fetched:
                strike = _to_int(
                    record.get("strikePrice", record.get("strike_price", 0))
                )
                ce_data = record.get("CE", record.get("callOption", {})) or {}
                pe_data = record.get("PE", record.get("putOption", {})) or {}

                rows.append(
                    _make_chain_row(strike, ce_data, pe_data)
                )

        # ---- Shape 2: flat list of dicts ----
        elif isinstance(raw_chain_data, list):
            logger.debug(
                f"build_option_chain_df: flat list with {len(raw_chain_data)} items."
            )
            # Group by strike
            strike_map: Dict[int, Dict] = {}
            for item in raw_chain_data:
                strike = _to_int(item.get("strikePrice", item.get("strike", 0)))
                opt_type = str(item.get("optiontype", item.get("option_type", ""))).upper()
                if strike not in strike_map:
                    strike_map[strike] = {"CE": {}, "PE": {}}
                if opt_type in ("CE", "PE"):
                    strike_map[strike][opt_type] = item

            for strike, opts in sorted(strike_map.items()):
                rows.append(
                    _make_chain_row(strike, opts["CE"], opts["PE"])
                )

        else:
            logger.warning(
                "build_option_chain_df: unrecognised raw_chain_data structure. "
                "Returning empty DataFrame."
            )
            return _empty_chain_df()

        if not rows:
            logger.warning("build_option_chain_df: no rows constructed.")
            return _empty_chain_df()

        df = pd.DataFrame(rows, columns=_CHAIN_COLUMNS)
        df.sort_values("strike", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # Type enforcement
        int_cols = ["strike", "ce_oi", "ce_oi_change", "ce_volume",
                    "pe_oi", "pe_oi_change", "pe_volume", "total_oi"]
        float_cols = ["ce_iv", "ce_ltp", "pe_iv", "pe_ltp"]

        for col in int_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        for col in float_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)

        df["total_oi"] = df["ce_oi"] + df["pe_oi"]

        logger.info(
            f"build_option_chain_df: {len(df)} strikes built. "
            f"Total CE OI={df['ce_oi'].sum():,}, PE OI={df['pe_oi'].sum():,}"
        )
        return df


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_CHAIN_COLUMNS = [
    "strike",
    "ce_oi", "ce_oi_change", "ce_iv", "ce_ltp", "ce_volume",
    "pe_oi", "pe_oi_change", "pe_iv", "pe_ltp", "pe_volume",
    "total_oi",
]


def _empty_chain_df() -> pd.DataFrame:
    """Return an empty DataFrame with the standard chain schema."""
    return pd.DataFrame(columns=_CHAIN_COLUMNS)


def _make_chain_row(
    strike: int,
    ce: Dict,
    pe: Dict,
) -> Dict:
    """
    Build a single chain row dict from raw CE and PE sub-dicts.

    Angel One field names differ slightly across endpoints; we try several
    common variants.
    """
    def _oi(d):
        return _to_int(d.get("openInterest", d.get("oi", d.get("open_interest", 0))))

    def _oi_chg(d):
        return _to_int(
            d.get("changeinOpenInterest",
                  d.get("oiChange",
                        d.get("change_in_oi", 0)))
        )

    def _iv(d):
        return _to_float(
            d.get("impliedVolatility",
                  d.get("iv", d.get("implied_volatility", 0.0)))
        )

    def _ltp(d):
        return _to_float(d.get("lastPrice", d.get("ltp", d.get("last_price", 0.0))))

    def _vol(d):
        return _to_int(d.get("totalTradedVolume", d.get("volume", d.get("vol", 0))))

    ce_oi = _oi(ce)
    pe_oi = _oi(pe)

    return {
        "strike":       strike,
        "ce_oi":        ce_oi,
        "ce_oi_change": _oi_chg(ce),
        "ce_iv":        _iv(ce),
        "ce_ltp":       _ltp(ce),
        "ce_volume":    _vol(ce),
        "pe_oi":        pe_oi,
        "pe_oi_change": _oi_chg(pe),
        "pe_iv":        _iv(pe),
        "pe_ltp":       _ltp(pe),
        "pe_volume":    _vol(pe),
        "total_oi":     ce_oi + pe_oi,
    }
