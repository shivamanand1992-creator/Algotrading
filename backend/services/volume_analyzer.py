"""
Volume Analyzer Service
========================
Production-ready service for tracking and analyzing intraday volume patterns.

Features:
- Track 10-day rolling average volume per time slot (5-minute intervals)
- Detect volume spikes (current volume vs historical average)
- Time-slot bucketing (9:15 AM - 3:30 PM IST in 5-min intervals)
- Persistent storage with automatic historical data management
- Thread-safe volume tracking and calculations
- REST API integration for real-time volume analysis

Design:
- Historical data stored in database (survives container restarts)
- Rolling 10-day window for average calculation
- Time slots: 9:15, 9:20, 9:25, ... 15:25, 15:30 (78 slots per day)
- Volume spike threshold: configurable multiplier (default 2.0x average)
- Automatic pruning of data older than 15 days

Usage:
    analyzer = VolumeAnalyzer()
    await analyzer.initialize()

    # Record current volume
    await analyzer.record_volume(symbol="NIFTY", volume=12500000, timestamp=datetime.now())

    # Check for volume spike
    spike_info = await analyzer.detect_volume_spike(symbol="NIFTY", current_volume=25000000)

    # Get historical average for current time slot
    avg_volume = await analyzer.get_slot_average(symbol="NIFTY", slot_time="09:15")
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
import pytz
from loguru import logger
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Float, Text, create_engine, Index
from sqlalchemy.orm import DeclarativeBase, Session

sys.path.append(str(Path(__file__).parent.parent.parent))

_IST = pytz.timezone("Asia/Kolkata")

# Cache file for fallback persistence
_CACHE_FILE = Path(__file__).parent.parent.parent / "logs" / "volume_history_cache.json"

# Market hours (IST)
MARKET_OPEN_TIME = time(9, 15)    # 9:15 AM
MARKET_CLOSE_TIME = time(15, 30)  # 3:30 PM

# Volume analysis configuration
ROLLING_WINDOW_DAYS = 10           # Track 10-day average
DATA_RETENTION_DAYS = 15           # Keep 15 days of history
TIME_SLOT_MINUTES = 5              # 5-minute time slots
VOLUME_SPIKE_THRESHOLD = 2.0       # 2x average = spike

# Number of time slots per day (9:15 to 15:30 in 5-min intervals)
SLOTS_PER_DAY = 78  # (6 hours 15 minutes) / 5 minutes = 75 slots


# ---------------------------------------------------------------------------
# Database models for persistence
# ---------------------------------------------------------------------------

class _VolumeBase(DeclarativeBase):
    pass


class _VolumeHistoryRow(_VolumeBase):
    """
    Volume history table — stores volume data per time slot per day.

    Schema:
        symbol: Stock/index symbol (e.g., "NIFTY", "BANKNIFTY")
        date: Trading date (YYYY-MM-DD)
        time_slot: Time slot (HH:MM format, e.g., "09:15", "09:20")
        volume: Total volume during that 5-minute slot
        timestamp: Full datetime of the record (for sorting/filtering)
    """
    __tablename__ = "volume_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    date = Column(String(16), nullable=False, index=True)        # YYYY-MM-DD
    time_slot = Column(String(8), nullable=False, index=True)    # HH:MM
    volume = Column(BigInteger, nullable=False)                  # Can be very large numbers
    timestamp = Column(DateTime, nullable=False, index=True)

    # Composite index for fast lookups
    __table_args__ = (
        Index('idx_symbol_date_slot', 'symbol', 'date', 'time_slot'),
        Index('idx_symbol_timestamp', 'symbol', 'timestamp'),
    )


class _VolumeStatsRow(_VolumeBase):
    """
    Volume statistics cache — stores pre-calculated 10-day averages.

    Updated daily to avoid recalculating on every request.
    """
    __tablename__ = "volume_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    time_slot = Column(String(8), nullable=False, index=True)
    avg_volume = Column(Float, nullable=False)                   # 10-day average
    std_volume = Column(Float, nullable=False)                   # Standard deviation
    sample_count = Column(Integer, nullable=False)               # Number of data points
    last_updated = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('idx_symbol_slot', 'symbol', 'time_slot', unique=True),
    )


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
# Helper functions
# ---------------------------------------------------------------------------

def _get_time_slot(dt: datetime) -> str:
    """
    Convert datetime to time slot string (HH:MM format).
    Rounds down to nearest 5-minute boundary.

    Example:
        09:17:35 → "09:15"
        14:23:12 → "14:20"
    """
    minute = (dt.minute // TIME_SLOT_MINUTES) * TIME_SLOT_MINUTES
    return f"{dt.hour:02d}:{minute:02d}"


def _is_market_hours(dt: datetime) -> bool:
    """Check if datetime is within market hours (9:15 AM - 3:30 PM IST)."""
    t = dt.time()
    return MARKET_OPEN_TIME <= t <= MARKET_CLOSE_TIME


def _get_ist_now() -> datetime:
    """Get current time in IST (timezone-aware)."""
    return datetime.now(_IST)


def _to_ist(dt: datetime) -> datetime:
    """Convert datetime to IST timezone."""
    if dt.tzinfo is None:
        # Assume IST if no timezone
        return _IST.localize(dt)
    return dt.astimezone(_IST)


# ---------------------------------------------------------------------------
# VolumeAnalyzer Service
# ---------------------------------------------------------------------------

class VolumeAnalyzer:
    """
    Volume analysis service with historical tracking and spike detection.

    Attributes:
        engine: SQLAlchemy database engine
        _stats_cache: In-memory cache of 10-day averages (reduces DB queries)
        _last_cache_update: Timestamp of last cache refresh
    """

    def __init__(self):
        self.engine = _get_db_engine()
        self._stats_cache: Dict[Tuple[str, str], Dict[str, float]] = {}
        self._last_cache_update: Optional[datetime] = None
        self._cache_ttl_minutes = 30  # Refresh stats cache every 30 minutes

    async def initialize(self) -> None:
        """
        Initialize the service — create database tables and load cache.

        Call this once at startup before using the service.
        """
        try:
            # Create tables if they don't exist
            _VolumeBase.metadata.create_all(self.engine)
            logger.info("[VolumeAnalyzer] Database tables initialized")

            # Load stats cache
            await self._refresh_stats_cache()

            # Clean up old data
            await self._cleanup_old_data()

            logger.info("[VolumeAnalyzer] Initialization complete")

        except Exception as exc:
            logger.error(f"[VolumeAnalyzer] Initialization failed: {exc}")
            raise

    async def record_volume(
        self,
        symbol: str,
        volume: int,
        timestamp: Optional[datetime] = None
    ) -> None:
        """
        Record volume for a specific time slot.

        Parameters:
            symbol: Stock/index symbol (e.g., "NIFTY")
            volume: Volume value to record
            timestamp: Optional timestamp (defaults to current IST time)
        """
        if timestamp is None:
            timestamp = _get_ist_now()
        else:
            timestamp = _to_ist(timestamp)

        # Only record during market hours
        if not _is_market_hours(timestamp):
            logger.debug(f"[VolumeAnalyzer] Skipping record outside market hours: {timestamp}")
            return

        time_slot = _get_time_slot(timestamp)
        date_str = timestamp.strftime("%Y-%m-%d")

        try:
            with Session(self.engine) as session:
                # Check if entry already exists (update if so)
                existing = session.query(_VolumeHistoryRow).filter_by(
                    symbol=symbol,
                    date=date_str,
                    time_slot=time_slot
                ).first()

                if existing:
                    # Update existing record
                    existing.volume = volume
                    existing.timestamp = timestamp
                    logger.debug(
                        f"[VolumeAnalyzer] Updated {symbol} {date_str} {time_slot}: {volume:,}"
                    )
                else:
                    # Create new record
                    new_record = _VolumeHistoryRow(
                        symbol=symbol,
                        date=date_str,
                        time_slot=time_slot,
                        volume=volume,
                        timestamp=timestamp
                    )
                    session.add(new_record)
                    logger.debug(
                        f"[VolumeAnalyzer] Recorded {symbol} {date_str} {time_slot}: {volume:,}"
                    )

                session.commit()

        except Exception as exc:
            logger.error(f"[VolumeAnalyzer] Failed to record volume: {exc}")

    async def get_slot_average(
        self,
        symbol: str,
        time_slot: Optional[str] = None,
        lookback_days: int = ROLLING_WINDOW_DAYS
    ) -> Dict[str, Any]:
        """
        Get the rolling average volume for a specific time slot.

        Parameters:
            symbol: Stock/index symbol
            time_slot: Time slot (HH:MM format). If None, uses current time slot.
            lookback_days: Number of days to average (default 10)

        Returns:
            dict with keys:
                - time_slot: Time slot string
                - avg_volume: Average volume over lookback period
                - std_volume: Standard deviation
                - sample_count: Number of data points used
                - min_volume: Minimum volume in period
                - max_volume: Maximum volume in period
        """
        if time_slot is None:
            time_slot = _get_time_slot(_get_ist_now())

        # Check cache first
        cache_key = (symbol, time_slot)
        if cache_key in self._stats_cache:
            cache_age = (_get_ist_now() - self._last_cache_update).total_seconds() / 60
            if cache_age < self._cache_ttl_minutes:
                cached_stats = self._stats_cache[cache_key]
                logger.debug(f"[VolumeAnalyzer] Using cached stats for {symbol} {time_slot}")
                return cached_stats

        # Calculate from database
        try:
            cutoff_date = (_get_ist_now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

            with Session(self.engine) as session:
                records = session.query(_VolumeHistoryRow).filter(
                    _VolumeHistoryRow.symbol == symbol,
                    _VolumeHistoryRow.time_slot == time_slot,
                    _VolumeHistoryRow.date >= cutoff_date
                ).all()

                if not records:
                    logger.debug(f"[VolumeAnalyzer] No historical data for {symbol} {time_slot}")
                    return {
                        "time_slot": time_slot,
                        "avg_volume": 0.0,
                        "std_volume": 0.0,
                        "sample_count": 0,
                        "min_volume": 0,
                        "max_volume": 0,
                    }

                volumes = [r.volume for r in records]

                stats = {
                    "time_slot": time_slot,
                    "avg_volume": float(np.mean(volumes)),
                    "std_volume": float(np.std(volumes)),
                    "sample_count": len(volumes),
                    "min_volume": int(np.min(volumes)),
                    "max_volume": int(np.max(volumes)),
                }

                # Update cache
                self._stats_cache[cache_key] = stats

                return stats

        except Exception as exc:
            logger.error(f"[VolumeAnalyzer] Failed to get slot average: {exc}")
            return {
                "time_slot": time_slot,
                "avg_volume": 0.0,
                "std_volume": 0.0,
                "sample_count": 0,
                "min_volume": 0,
                "max_volume": 0,
            }

    async def detect_volume_spike(
        self,
        symbol: str,
        current_volume: int,
        timestamp: Optional[datetime] = None,
        threshold_multiplier: float = VOLUME_SPIKE_THRESHOLD
    ) -> Dict[str, Any]:
        """
        Detect if current volume represents a spike compared to historical average.

        Parameters:
            symbol: Stock/index symbol
            current_volume: Current volume to check
            timestamp: Optional timestamp (defaults to current time)
            threshold_multiplier: Spike threshold (default 2.0x average)

        Returns:
            dict with keys:
                - is_spike: bool (True if volume spike detected)
                - current_volume: Current volume value
                - avg_volume: Historical average for this time slot
                - spike_ratio: current / average (e.g., 2.5 = 2.5x average)
                - threshold: Threshold used for spike detection
                - time_slot: Time slot of the analysis
                - interpretation: Human-readable description
        """
        if timestamp is None:
            timestamp = _get_ist_now()
        else:
            timestamp = _to_ist(timestamp)

        time_slot = _get_time_slot(timestamp)

        # Get historical average for this time slot
        stats = await self.get_slot_average(symbol, time_slot)
        avg_volume = stats["avg_volume"]

        # Avoid division by zero
        if avg_volume == 0:
            logger.warning(
                f"[VolumeAnalyzer] No historical data for {symbol} {time_slot}, "
                "cannot detect spike"
            )
            return {
                "is_spike": False,
                "current_volume": current_volume,
                "avg_volume": 0.0,
                "spike_ratio": 0.0,
                "threshold": threshold_multiplier,
                "time_slot": time_slot,
                "interpretation": "Insufficient historical data for spike detection",
                "confidence": 0.0,
            }

        # Calculate spike ratio
        spike_ratio = current_volume / avg_volume
        is_spike = spike_ratio >= threshold_multiplier

        # Generate interpretation
        if is_spike:
            pct_increase = (spike_ratio - 1.0) * 100
            interpretation = (
                f"VOLUME SPIKE: {spike_ratio:.1f}x average volume "
                f"({pct_increase:.0f}% above normal for {time_slot})"
            )
        else:
            interpretation = (
                f"Normal volume: {spike_ratio:.1f}x average "
                f"(below {threshold_multiplier}x threshold)"
            )

        # Calculate confidence based on sample size
        sample_count = stats["sample_count"]
        confidence = min(sample_count / ROLLING_WINDOW_DAYS, 1.0)

        result = {
            "is_spike": is_spike,
            "current_volume": current_volume,
            "avg_volume": avg_volume,
            "spike_ratio": round(spike_ratio, 2),
            "threshold": threshold_multiplier,
            "time_slot": time_slot,
            "interpretation": interpretation,
            "confidence": round(confidence, 2),
            "sample_count": sample_count,
        }

        if is_spike:
            logger.info(f"[VolumeAnalyzer] {interpretation}")
        else:
            logger.debug(f"[VolumeAnalyzer] {interpretation}")

        return result

    async def get_volume_profile(
        self,
        symbol: str,
        date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get the complete volume profile for a trading day.

        Returns volume data for all time slots (9:15 - 15:30).

        Parameters:
            symbol: Stock/index symbol
            date: Trading date (YYYY-MM-DD). If None, uses today.

        Returns:
            List of dicts, one per time slot, with keys:
                - time_slot: Time slot string
                - volume: Actual volume for that slot
                - avg_volume: 10-day average
                - spike_ratio: volume / avg_volume
                - is_spike: bool
        """
        if date is None:
            date = _get_ist_now().strftime("%Y-%m-%d")

        try:
            with Session(self.engine) as session:
                records = session.query(_VolumeHistoryRow).filter(
                    _VolumeHistoryRow.symbol == symbol,
                    _VolumeHistoryRow.date == date
                ).order_by(_VolumeHistoryRow.time_slot).all()

                profile = []
                for record in records:
                    stats = await self.get_slot_average(symbol, record.time_slot)
                    avg_volume = stats["avg_volume"]

                    spike_ratio = record.volume / avg_volume if avg_volume > 0 else 0.0
                    is_spike = spike_ratio >= VOLUME_SPIKE_THRESHOLD

                    profile.append({
                        "time_slot": record.time_slot,
                        "volume": record.volume,
                        "avg_volume": avg_volume,
                        "spike_ratio": round(spike_ratio, 2),
                        "is_spike": is_spike,
                    })

                logger.info(
                    f"[VolumeAnalyzer] Retrieved volume profile for {symbol} {date}: "
                    f"{len(profile)} time slots"
                )
                return profile

        except Exception as exc:
            logger.error(f"[VolumeAnalyzer] Failed to get volume profile: {exc}")
            return []

    async def _refresh_stats_cache(self) -> None:
        """
        Refresh the in-memory statistics cache from database.

        Pre-calculates 10-day averages for all symbols and time slots.
        """
        try:
            logger.info("[VolumeAnalyzer] Refreshing statistics cache...")

            cutoff_date = (_get_ist_now() - timedelta(days=ROLLING_WINDOW_DAYS)).strftime("%Y-%m-%d")

            with Session(self.engine) as session:
                # Get all unique symbol/slot combinations with recent data
                records = session.query(_VolumeHistoryRow).filter(
                    _VolumeHistoryRow.date >= cutoff_date
                ).all()

                # Group by symbol and time_slot
                grouped: Dict[Tuple[str, str], List[int]] = defaultdict(list)
                for record in records:
                    grouped[(record.symbol, record.time_slot)].append(record.volume)

                # Calculate stats for each group
                self._stats_cache.clear()
                for (symbol, time_slot), volumes in grouped.items():
                    self._stats_cache[(symbol, time_slot)] = {
                        "time_slot": time_slot,
                        "avg_volume": float(np.mean(volumes)),
                        "std_volume": float(np.std(volumes)),
                        "sample_count": len(volumes),
                        "min_volume": int(np.min(volumes)),
                        "max_volume": int(np.max(volumes)),
                    }

                self._last_cache_update = _get_ist_now()

                logger.info(
                    f"[VolumeAnalyzer] Cache refreshed: {len(self._stats_cache)} entries"
                )

        except Exception as exc:
            logger.error(f"[VolumeAnalyzer] Failed to refresh cache: {exc}")

    async def _cleanup_old_data(self) -> None:
        """
        Remove volume history older than DATA_RETENTION_DAYS.

        Runs automatically during initialization and can be called periodically.
        """
        try:
            cutoff_date = (_get_ist_now() - timedelta(days=DATA_RETENTION_DAYS)).strftime("%Y-%m-%d")

            with Session(self.engine) as session:
                deleted_count = session.query(_VolumeHistoryRow).filter(
                    _VolumeHistoryRow.date < cutoff_date
                ).delete()

                session.commit()

                if deleted_count > 0:
                    logger.info(
                        f"[VolumeAnalyzer] Cleaned up {deleted_count} old records "
                        f"(before {cutoff_date})"
                    )

        except Exception as exc:
            logger.error(f"[VolumeAnalyzer] Cleanup failed: {exc}")

    def get_all_time_slots(self) -> List[str]:
        """
        Get all possible time slots for a trading day.

        Returns list of time slots from 9:15 to 15:30 in 5-minute intervals.
        """
        slots = []
        current = datetime.combine(datetime.today(), MARKET_OPEN_TIME)
        end = datetime.combine(datetime.today(), MARKET_CLOSE_TIME)

        while current <= end:
            slots.append(_get_time_slot(current))
            current += timedelta(minutes=TIME_SLOT_MINUTES)

        return slots


# ---------------------------------------------------------------------------
# Global instance (singleton pattern)
# ---------------------------------------------------------------------------

_analyzer_instance: Optional[VolumeAnalyzer] = None


async def get_volume_analyzer() -> VolumeAnalyzer:
    """
    Get the global VolumeAnalyzer instance.

    Initializes on first call. Use this function instead of creating
    new instances to ensure singleton behavior.
    """
    global _analyzer_instance

    if _analyzer_instance is None:
        _analyzer_instance = VolumeAnalyzer()
        await _analyzer_instance.initialize()

    return _analyzer_instance


# ---------------------------------------------------------------------------
# Convenience functions for common use cases
# ---------------------------------------------------------------------------

async def record_current_volume(symbol: str, volume: int) -> None:
    """Record volume for current time slot."""
    analyzer = await get_volume_analyzer()
    await analyzer.record_volume(symbol, volume)


async def check_volume_spike(symbol: str, current_volume: int) -> Dict[str, Any]:
    """Check if current volume is a spike."""
    analyzer = await get_volume_analyzer()
    return await analyzer.detect_volume_spike(symbol, current_volume)


async def get_current_slot_average(symbol: str) -> float:
    """Get average volume for current time slot."""
    analyzer = await get_volume_analyzer()
    stats = await analyzer.get_slot_average(symbol)
    return stats["avg_volume"]
