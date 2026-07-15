"""
support_resistance_service.py
==============================
Production-ready Support & Resistance Level Detection Service

Features:
- Calculate S/R levels from last 3 days OHLC data
- Daily automatic refresh at 9:00 AM IST
- Level validation with strength scoring
- REST API endpoint for current levels
- Persistence (database + file fallback)
- Multi-algorithm support (pivot points, swing highs/lows, volume profile)

Algorithm: Swing High/Low + Pivot Points hybrid approach
- Identifies turning points in price action over 3-day window
- Clusters nearby levels to avoid redundancy
- Scores levels by touch frequency, volume, and recency
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz
from loguru import logger
from sqlalchemy import Column, String, Integer, Float, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

sys.path.append(str(Path(__file__).parent.parent.parent))

_IST = pytz.timezone("Asia/Kolkata")

_CACHE_FILE = Path(__file__).parent.parent.parent / "logs" / "sr_levels_cache.json"


# ---------------------------------------------------------------------------
# Database model for persistence (survives Railway container restarts)
# ---------------------------------------------------------------------------

class _SRBase(DeclarativeBase):
    pass


class _SRLevelRow(_SRBase):
    """Support/Resistance levels table — persists calculated levels."""
    __tablename__ = "sr_levels"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    symbol      = Column(String(32),  nullable=False, index=True)
    level_type  = Column(String(16),  nullable=False)  # "support" | "resistance"
    price       = Column(Float,       nullable=False)
    strength    = Column(Float,       nullable=False)  # 0.0–1.0 confidence score
    touches     = Column(Integer,     nullable=False, default=1)
    last_touch  = Column(String(32),  nullable=False)  # ISO timestamp
    calculated  = Column(String(32),  nullable=False)  # ISO timestamp of calculation
    metadata    = Column(Text,        nullable=False, default="{}")  # JSON extras


def _get_db_engine():
    """Return SQLAlchemy engine (Postgres on Railway, SQLite locally)."""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        logs_dir = Path(__file__).parent.parent.parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{logs_dir}/trades.db"
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    return create_engine(db_url, echo=False, future=True, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# Support/Resistance Detection Algorithms
# ---------------------------------------------------------------------------

def _detect_swing_levels(
    df: pd.DataFrame,
    swing_window: int = 5,
    min_distance_pct: float = 0.5,
) -> List[dict]:
    """
    Identify swing highs and swing lows from OHLC data.

    A swing high: highest high in a window of `swing_window` candles on each side.
    A swing low:  lowest low in a window of `swing_window` candles on each side.

    Returns:
        List of {"type": "support"|"resistance", "price": float, "timestamp": str, "volume": float}
    """
    if df is None or df.empty or len(df) < swing_window * 2 + 1:
        return []

    levels = []
    highs = df["high"].values
    lows = df["low"].values
    volumes = df["volume"].values if "volume" in df.columns else np.zeros(len(df))
    timestamps = df["timestamp"].values if "timestamp" in df.columns else [str(i) for i in range(len(df))]

    n = len(df)

    # Find swing highs (local maxima)
    for i in range(swing_window, n - swing_window):
        window_highs = highs[i - swing_window : i + swing_window + 1]
        if highs[i] == max(window_highs):
            levels.append({
                "type": "resistance",
                "price": float(highs[i]),
                "timestamp": str(timestamps[i]),
                "volume": float(volumes[i]),
            })

    # Find swing lows (local minima)
    for i in range(swing_window, n - swing_window):
        window_lows = lows[i - swing_window : i + swing_window + 1]
        if lows[i] == min(window_lows):
            levels.append({
                "type": "support",
                "price": float(lows[i]),
                "timestamp": str(timestamps[i]),
                "volume": float(volumes[i]),
            })

    return levels


def _calculate_pivot_points(df: pd.DataFrame) -> List[dict]:
    """
    Classic Pivot Points from previous day's OHLC.

    PP = (H + L + C) / 3
    R1 = 2×PP − L
    R2 = PP + (H − L)
    S1 = 2×PP − H
    S2 = PP − (H − L)

    Returns:
        List of pivot levels with type and price
    """
    if df is None or df.empty:
        return []

    # Use last complete candle (most recent closed bar)
    last_row = df.iloc[-1]
    h = float(last_row["high"])
    l = float(last_row["low"])
    c = float(last_row["close"])

    pp = (h + l + c) / 3
    r1 = 2 * pp - l
    r2 = pp + (h - l)
    r3 = h + 2 * (pp - l)
    s1 = 2 * pp - h
    s2 = pp - (h - l)
    s3 = l - 2 * (h - pp)

    return [
        {"type": "resistance", "price": r3, "label": "R3", "method": "pivot"},
        {"type": "resistance", "price": r2, "label": "R2", "method": "pivot"},
        {"type": "resistance", "price": r1, "label": "R1", "method": "pivot"},
        {"type": "neutral",    "price": pp, "label": "PP", "method": "pivot"},
        {"type": "support",    "price": s1, "label": "S1", "method": "pivot"},
        {"type": "support",    "price": s2, "label": "S2", "method": "pivot"},
        {"type": "support",    "price": s3, "label": "S3", "method": "pivot"},
    ]


def _cluster_levels(
    levels: List[dict],
    cluster_pct: float = 0.3,
) -> List[dict]:
    """
    Cluster nearby price levels to avoid redundancy.

    Levels within `cluster_pct` % of each other are merged into one,
    taking the volume-weighted average price.

    Returns:
        De-duplicated list of levels with aggregated metadata
    """
    if not levels:
        return []

    # Sort by price
    sorted_levels = sorted(levels, key=lambda x: x["price"])

    clusters = []
    current_cluster = [sorted_levels[0]]

    for level in sorted_levels[1:]:
        # Check if level is within cluster_pct of current cluster's average
        cluster_avg = np.mean([lv["price"] for lv in current_cluster])
        pct_diff = abs(level["price"] - cluster_avg) / cluster_avg * 100

        if pct_diff <= cluster_pct:
            current_cluster.append(level)
        else:
            # Finalize current cluster and start a new one
            clusters.append(current_cluster)
            current_cluster = [level]

    # Add last cluster
    if current_cluster:
        clusters.append(current_cluster)

    # Merge each cluster into a single level
    merged = []
    for cluster in clusters:
        total_volume = sum(lv.get("volume", 1.0) for lv in cluster)
        if total_volume == 0:
            total_volume = 1.0

        # Volume-weighted average price
        avg_price = sum(lv["price"] * lv.get("volume", 1.0) for lv in cluster) / total_volume

        # Majority vote for type
        type_counts = defaultdict(int)
        for lv in cluster:
            type_counts[lv["type"]] += 1
        level_type = max(type_counts, key=type_counts.get)

        # Touch count
        touches = len(cluster)

        # Most recent timestamp
        timestamps = [lv.get("timestamp", "") for lv in cluster if lv.get("timestamp")]
        last_touch = max(timestamps) if timestamps else datetime.now(_IST).isoformat()

        merged.append({
            "type": level_type,
            "price": round(avg_price, 2),
            "touches": touches,
            "last_touch": last_touch,
            "volume": round(total_volume, 2),
        })

    return merged


def _score_levels(
    levels: List[dict],
    current_price: float,
    lookback_hours: int = 72,
) -> List[dict]:
    """
    Score each S/R level by:
    - Touch frequency (more touches = stronger)
    - Recency (recent touches scored higher)
    - Volume at level (higher volume = more significant)
    - Proximity to current price (levels too far away are less relevant)

    Returns:
        Levels with added "strength" field (0.0–1.0)
    """
    if not levels:
        return []

    now = datetime.now(_IST)
    max_touches = max(lv.get("touches", 1) for lv in levels)
    max_volume = max(lv.get("volume", 1.0) for lv in levels)

    scored = []
    for lv in levels:
        touches = lv.get("touches", 1)
        volume = lv.get("volume", 1.0)
        last_touch_str = lv.get("last_touch", "")

        # Recency score (0.0–1.0): exponential decay over lookback period
        try:
            last_touch = datetime.fromisoformat(last_touch_str.replace("Z", "+00:00"))
            if last_touch.tzinfo is None:
                last_touch = _IST.localize(last_touch)
            hours_ago = (now - last_touch).total_seconds() / 3600
            recency_score = np.exp(-hours_ago / lookback_hours)
        except Exception:
            recency_score = 0.5

        # Touch score (0.0–1.0): normalized by max touches
        touch_score = touches / max_touches if max_touches > 0 else 0.5

        # Volume score (0.0–1.0): normalized by max volume
        volume_score = volume / max_volume if max_volume > 0 else 0.5

        # Proximity score (0.0–1.0): levels within ±5% of current price score higher
        distance_pct = abs(lv["price"] - current_price) / current_price * 100
        proximity_score = max(0.0, 1.0 - distance_pct / 10.0)  # linear decay over 10%

        # Composite strength: weighted average
        strength = (
            0.3 * touch_score +
            0.3 * recency_score +
            0.2 * volume_score +
            0.2 * proximity_score
        )
        strength = max(0.0, min(1.0, strength))

        lv["strength"] = round(strength, 3)
        scored.append(lv)

    # Sort by strength descending
    scored.sort(key=lambda x: x["strength"], reverse=True)

    return scored


# ---------------------------------------------------------------------------
# Service Class
# ---------------------------------------------------------------------------

class SupportResistanceService:
    """
    Calculate, cache, and serve Support/Resistance levels for Nifty/stocks.

    Features:
    - 3-day OHLC data fetch (Angel One primary, Yahoo Finance fallback)
    - Hybrid algorithm: swing highs/lows + pivot points
    - Level clustering to avoid noise
    - Strength scoring based on touches, recency, volume, proximity
    - Auto-refresh at 9:00 AM IST daily
    - Persistence via PostgreSQL (Railway-safe) + file fallback
    """

    def __init__(self, angel_client=None):
        self.angel_client = angel_client
        self._cache: Dict[str, dict] = {}  # symbol → {"levels": [...], "calculated_at": ISO timestamp}
        self._last_refresh: Optional[datetime] = None
        self._load_cache()
        logger.info("[SupportResistanceService] Initialized.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_levels(
        self,
        symbol: str = "NIFTY",
        force_refresh: bool = False,
    ) -> dict:
        """
        Get current support/resistance levels for a symbol.

        Returns:
            {
                "symbol": str,
                "current_price": float,
                "support_levels": [{"price": float, "strength": float, "touches": int}, ...],
                "resistance_levels": [...],
                "pivot_points": {...},
                "calculated_at": ISO timestamp,
                "next_refresh": ISO timestamp (9:00 AM IST next day),
            }
        """
        now_ist = datetime.now(_IST)

        # Check cache freshness — refresh if stale or forced
        cached = self._cache.get(symbol)
        if cached and not force_refresh:
            calc_time = datetime.fromisoformat(cached["calculated_at"])
            age_hours = (now_ist - calc_time).total_seconds() / 3600
            if age_hours < 24:  # cache valid for 24h
                logger.debug(f"[SR] Returning cached levels for {symbol} (age: {age_hours:.1f}h)")
                return cached

        # Fetch fresh OHLC and calculate levels
        logger.info(f"[SR] Calculating fresh levels for {symbol}…")
        df = await self._fetch_ohlc(symbol, days=3)
        if df is None or df.empty:
            logger.warning(f"[SR] No OHLC data for {symbol} — cannot calculate levels.")
            return self._empty_response(symbol)

        current_price = float(df.iloc[-1]["close"]) if not df.empty else 0.0

        # Algorithm: swing highs/lows + pivot points
        swing_levels = _detect_swing_levels(df, swing_window=5, min_distance_pct=0.5)
        pivot_levels = _calculate_pivot_points(df)

        # Merge and cluster
        all_levels = swing_levels + [
            {"type": lv["type"], "price": lv["price"], "timestamp": now_ist.isoformat(), "volume": 0.0}
            for lv in pivot_levels if lv["type"] != "neutral"
        ]
        clustered = _cluster_levels(all_levels, cluster_pct=0.3)

        # Score by strength
        scored = _score_levels(clustered, current_price, lookback_hours=72)

        # Separate support and resistance
        supports = [lv for lv in scored if lv["type"] == "support"]
        resistances = [lv for lv in scored if lv["type"] == "resistance"]

        # Extract pivot point dict for quick reference
        pivot_dict = {lv["label"]: round(lv["price"], 2) for lv in pivot_levels}

        result = {
            "symbol": symbol,
            "current_price": round(current_price, 2),
            "support_levels": [
                {
                    "price": lv["price"],
                    "strength": lv["strength"],
                    "touches": lv["touches"],
                    "last_touch": lv["last_touch"],
                }
                for lv in supports
            ],
            "resistance_levels": [
                {
                    "price": lv["price"],
                    "strength": lv["strength"],
                    "touches": lv["touches"],
                    "last_touch": lv["last_touch"],
                }
                for lv in resistances
            ],
            "pivot_points": pivot_dict,
            "calculated_at": now_ist.isoformat(),
            "next_refresh": self._next_refresh_time(now_ist).isoformat(),
        }

        # Cache and persist
        self._cache[symbol] = result
        self._save_cache()
        await self._persist_to_db(symbol, supports, resistances, now_ist)

        logger.info(
            f"[SR] {symbol}: {len(supports)} support, {len(resistances)} resistance levels "
            f"(current: ₹{current_price:.2f})"
        )

        return result

    async def refresh_daily(self, symbols: List[str] = None) -> dict:
        """
        Daily refresh job — recalculate levels for all tracked symbols.
        Called by scheduler at 9:00 AM IST.

        Args:
            symbols: list of symbols to refresh (default: ["NIFTY"])

        Returns:
            {"refreshed": int, "symbols": [...], "timestamp": ISO}
        """
        if symbols is None:
            symbols = ["NIFTY"]

        logger.info(f"[SR] Daily refresh starting for {len(symbols)} symbol(s)…")

        refreshed = []
        for symbol in symbols:
            try:
                await self.get_levels(symbol, force_refresh=True)
                refreshed.append(symbol)
            except Exception as exc:
                logger.error(f"[SR] Daily refresh failed for {symbol}: {exc}")

        self._last_refresh = datetime.now(_IST)

        logger.info(f"[SR] Daily refresh complete — {len(refreshed)}/{len(symbols)} symbols updated.")

        return {
            "refreshed": len(refreshed),
            "symbols": refreshed,
            "timestamp": self._last_refresh.isoformat(),
        }

    def validate_level(self, symbol: str, price: float, tolerance_pct: float = 0.5) -> dict:
        """
        Check if a price is near a known S/R level.

        Args:
            symbol: stock/index symbol
            price: price to validate
            tolerance_pct: % distance to consider "at level"

        Returns:
            {
                "is_at_level": bool,
                "level_type": "support" | "resistance" | None,
                "nearest_level": float | None,
                "distance_pct": float,
                "strength": float,
            }
        """
        cached = self._cache.get(symbol)
        if not cached:
            return {
                "is_at_level": False,
                "level_type": None,
                "nearest_level": None,
                "distance_pct": 0.0,
                "strength": 0.0,
            }

        all_levels = cached["support_levels"] + cached["resistance_levels"]
        if not all_levels:
            return {
                "is_at_level": False,
                "level_type": None,
                "nearest_level": None,
                "distance_pct": 0.0,
                "strength": 0.0,
            }

        # Find nearest level
        nearest = min(all_levels, key=lambda lv: abs(lv["price"] - price))
        distance_pct = abs(nearest["price"] - price) / price * 100
        is_at_level = distance_pct <= tolerance_pct

        level_type = "support" if nearest in cached["support_levels"] else "resistance"

        return {
            "is_at_level": is_at_level,
            "level_type": level_type if is_at_level else None,
            "nearest_level": nearest["price"],
            "distance_pct": round(distance_pct, 2),
            "strength": nearest["strength"],
        }

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    async def _fetch_ohlc(self, symbol: str, days: int = 3) -> Optional[pd.DataFrame]:
        """
        Fetch OHLC data for a symbol (Angel One primary, Yahoo Finance fallback).

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        loop = asyncio.get_event_loop()

        # Angel One (15-min candles, aggregated to daily)
        if self.angel_client and symbol == "NIFTY":
            try:
                from datetime import timedelta
                now = datetime.now(_IST)
                f_date = (now - timedelta(days=days)).strftime("%Y-%m-%d 09:15")
                t_date = now.strftime("%Y-%m-%d %H:%M")

                hist = await loop.run_in_executor(
                    None,
                    self.angel_client.get_historical_data,
                    "NSE", "26000", "FIFTEEN_MINUTE", f_date, t_date,
                )

                if hist is not None and not hist.empty:
                    # Resample 15-min → daily OHLC
                    hist = hist.set_index("timestamp")
                    daily = pd.DataFrame({
                        "open": hist["open"].resample("1D").first(),
                        "high": hist["high"].resample("1D").max(),
                        "low": hist["low"].resample("1D").min(),
                        "close": hist["close"].resample("1D").last(),
                        "volume": hist["volume"].resample("1D").sum(),
                    }).reset_index()
                    daily = daily.dropna()
                    if not daily.empty:
                        logger.debug(f"[SR] Fetched {len(daily)} daily candles from Angel One for {symbol}.")
                        return daily
            except Exception as exc:
                logger.warning(f"[SR] Angel One fetch failed for {symbol}: {exc}")

        # Yahoo Finance fallback
        try:
            import yfinance as yf

            ticker_map = {
                "NIFTY": "^NSEI",
                "BANKNIFTY": "^NSEBANK",
            }
            yf_ticker = ticker_map.get(symbol, f"{symbol}.NS")

            df = await loop.run_in_executor(
                None,
                lambda: yf.Ticker(yf_ticker).history(period=f"{days}d", interval="1d")
            )

            if df is None or df.empty:
                return None

            # Normalize column names
            if hasattr(df.columns, "get_level_values"):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]

            df = df.reset_index()
            df = df.rename(columns={"date": "timestamp"})

            # Localize to IST
            if "timestamp" in df.columns:
                if df["timestamp"].dt.tz is None:
                    df["timestamp"] = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert(_IST)
                else:
                    df["timestamp"] = df["timestamp"].dt.tz_convert(_IST)

            logger.debug(f"[SR] Fetched {len(df)} daily candles from Yahoo Finance for {symbol}.")
            return df

        except Exception as exc:
            logger.error(f"[SR] Yahoo Finance fetch failed for {symbol}: {exc}")
            return None

    def _next_refresh_time(self, now: datetime) -> datetime:
        """Return next 9:00 AM IST refresh time."""
        next_refresh = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now.hour >= 9:
            next_refresh += timedelta(days=1)
        return next_refresh

    def _empty_response(self, symbol: str) -> dict:
        """Return empty S/R response when data unavailable."""
        now_ist = datetime.now(_IST)
        return {
            "symbol": symbol,
            "current_price": 0.0,
            "support_levels": [],
            "resistance_levels": [],
            "pivot_points": {},
            "calculated_at": now_ist.isoformat(),
            "next_refresh": self._next_refresh_time(now_ist).isoformat(),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_cache(self) -> None:
        """Load cached levels from file (fallback when DB unavailable)."""
        if not _CACHE_FILE.exists():
            return
        try:
            data = json.loads(_CACHE_FILE.read_text())
            self._cache = data.get("cache", {})
            logger.info(f"[SR] Loaded cache from file — {len(self._cache)} symbol(s).")
        except Exception as exc:
            logger.warning(f"[SR] Could not load cache file: {exc}")

    def _save_cache(self) -> None:
        """Save cache to file (secondary persistence)."""
        try:
            _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_FILE.write_text(json.dumps({"cache": self._cache}, indent=2, default=str))
        except Exception as exc:
            logger.warning(f"[SR] Could not save cache file: {exc}")

    async def _persist_to_db(
        self,
        symbol: str,
        supports: List[dict],
        resistances: List[dict],
        calculated_at: datetime,
    ) -> None:
        """Write S/R levels to database (primary persistence, survives Railway redeploys)."""
        try:
            engine = _get_db_engine()
            _SRBase.metadata.create_all(engine, checkfirst=True)

            loop = asyncio.get_event_loop()

            def _write():
                with Session(engine) as s:
                    # Clear old levels for this symbol
                    s.query(_SRLevelRow).filter(_SRLevelRow.symbol == symbol).delete()

                    # Insert new levels
                    for lv in supports:
                        s.add(_SRLevelRow(
                            symbol=symbol,
                            level_type="support",
                            price=lv["price"],
                            strength=lv["strength"],
                            touches=lv["touches"],
                            last_touch=lv["last_touch"],
                            calculated=calculated_at.isoformat(),
                            metadata=json.dumps({}),
                        ))

                    for lv in resistances:
                        s.add(_SRLevelRow(
                            symbol=symbol,
                            level_type="resistance",
                            price=lv["price"],
                            strength=lv["strength"],
                            touches=lv["touches"],
                            last_touch=lv["last_touch"],
                            calculated=calculated_at.isoformat(),
                            metadata=json.dumps({}),
                        ))

                    s.commit()

            await loop.run_in_executor(None, _write)
            logger.debug(f"[SR] Persisted {len(supports) + len(resistances)} levels to DB for {symbol}.")

        except Exception as exc:
            logger.warning(f"[SR] DB persist failed for {symbol}: {exc}")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_sr_service_instance: Optional[SupportResistanceService] = None


def get_sr_service(angel_client=None) -> SupportResistanceService:
    """Get or create the singleton SupportResistanceService instance."""
    global _sr_service_instance
    if _sr_service_instance is None:
        _sr_service_instance = SupportResistanceService(angel_client)
    return _sr_service_instance
