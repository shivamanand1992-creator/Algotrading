"""
Intraday Setup Detector Service
=================================
Production-ready service for detecting high-probability intraday trading setups.

Features:
- Three core setup patterns: Opening Breakout, Retest, Consolidation Break
- Real-time pattern recognition on live candle data
- Price action + volume validation for each setup
- Dynamic entry, stop-loss, and target calculation
- Setup strength scoring (0.0 - 1.0 confidence)
- Alert emission system with detailed setup metadata
- Thread-safe setup tracking and deduplication
- REST API integration for setup queries
- Persistent setup logging and analytics

Setup Patterns:
---------------

1. Opening Breakout (ORB):
   - Identifies range formed in first 15-30 minutes
   - Triggers on breakout with strong volume
   - Entry: Breakout level + buffer
   - SL: Opposite end of opening range
   - Targets: R:R based (1.5:1, 2:1, 3:1)

2. Retest Setup:
   - Detects pullback to previous support/resistance level
   - Validates price rejection and volume confirmation
   - Entry: After bounce confirmation
   - SL: Below/above the tested level
   - Targets: Previous swing high/low

3. Consolidation Break:
   - Identifies tight consolidation zones (low volatility)
   - Triggers on breakout with volume expansion
   - Entry: Breakout level with confirmation
   - SL: Inside consolidation range
   - Targets: Projected move (range width extension)

Algorithm:
----------
- Maintains rolling window of candles for pattern detection
- Tracks price swings, support/resistance levels
- Volume analysis: compares current vs average volume
- Pattern validation: minimum criteria (time, price action, volume)
- Setup deduplication: avoid repeat alerts for same setup
- Real-time monitoring: callback-based alert system

Usage:
------
    detector = IntradaySetupDetector(
        intraday_service=intraday_data_service,
        sr_service=support_resistance_service,
        volume_analyzer=volume_analyzer
    )
    await detector.initialize()

    # Register alert callback
    detector.register_alert_callback(on_setup_detected)

    # Get current active setups
    setups = await detector.get_active_setups(symbol="NIFTY")
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, time
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable, Any

import numpy as np
import pandas as pd
import pytz
from loguru import logger
from sqlalchemy import Column, String, Integer, Float, DateTime, Text, Boolean, create_engine, Index
from sqlalchemy.orm import DeclarativeBase, Session

sys.path.append(str(Path(__file__).parent.parent.parent))

_IST = pytz.timezone("Asia/Kolkata")

# Cache file for setup persistence
_CACHE_FILE = Path(__file__).parent.parent.parent / "logs" / "intraday_setups_cache.json"

# Market hours (IST)
MARKET_OPEN_TIME = time(9, 15)    # 9:15 AM
MARKET_CLOSE_TIME = time(15, 30)  # 3:30 PM

# Setup detection configuration
OPENING_RANGE_DURATION_MIN = 15   # First 15 minutes for ORB
OPENING_RANGE_MAX_DURATION = 30   # Max 30 minutes for opening range
CONSOLIDATION_MIN_CANDLES = 10    # Minimum candles for consolidation
CONSOLIDATION_ATR_THRESHOLD = 0.3  # ATR ratio for tight consolidation
VOLUME_SPIKE_THRESHOLD = 1.5      # 1.5x average volume for breakouts
MIN_SETUP_CONFIDENCE = 0.6        # Minimum confidence to emit alert
RETEST_TOLERANCE_PCT = 0.3        # 0.3% tolerance for S/R retest
SETUP_EXPIRY_MINUTES = 60         # Setups expire after 60 minutes


# ---------------------------------------------------------------------------
# Enums and Data Structures
# ---------------------------------------------------------------------------

class SetupType(str, Enum):
    """Trading setup pattern types"""
    OPENING_BREAKOUT = "opening_breakout"
    RETEST = "retest"
    CONSOLIDATION_BREAK = "consolidation_break"


class Direction(str, Enum):
    """Trade direction"""
    LONG = "long"
    SHORT = "short"


@dataclass
class SetupAlert:
    """
    Trading setup alert with complete setup details.

    Attributes:
        setup_id: Unique identifier for this setup
        setup_type: Type of setup pattern
        symbol: Trading symbol
        direction: Long or short
        timestamp: When setup was detected
        trigger_price: Price that triggered the setup
        entry_price: Recommended entry price
        stop_loss: Stop loss price
        targets: List of target prices [T1, T2, T3]
        confidence: Setup strength score (0.0 - 1.0)
        volume_ratio: Current volume vs average
        metadata: Additional setup-specific data
        active: Whether setup is still valid
        triggered_at: When entry was triggered (if any)
    """
    setup_id: str
    setup_type: SetupType
    symbol: str
    direction: Direction
    timestamp: datetime
    trigger_price: float
    entry_price: float
    stop_loss: float
    targets: List[float]
    confidence: float
    volume_ratio: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    active: bool = True
    triggered_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary with ISO timestamps"""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        d["setup_type"] = self.setup_type.value
        d["direction"] = self.direction.value
        if self.triggered_at:
            d["triggered_at"] = self.triggered_at.isoformat()
        return d

    def risk_reward_ratio(self) -> float:
        """Calculate risk:reward ratio for first target"""
        risk = abs(self.entry_price - self.stop_loss)
        if risk == 0:
            return 0.0
        reward = abs(self.targets[0] - self.entry_price) if self.targets else 0.0
        return reward / risk


@dataclass
class PriceSwing:
    """Price swing high/low point"""
    price: float
    timestamp: datetime
    swing_type: str  # "high" or "low"
    volume: int


# ---------------------------------------------------------------------------
# Database models for persistence
# ---------------------------------------------------------------------------

class _SetupBase(DeclarativeBase):
    pass


class _SetupAlertRow(_SetupBase):
    """
    Setup alerts table — stores detected trading setups.

    Schema:
        setup_id: Unique identifier
        setup_type: Pattern type (opening_breakout, retest, consolidation_break)
        symbol: Trading symbol
        direction: long/short
        timestamp: Detection time
        trigger_price: Trigger price
        entry_price: Entry recommendation
        stop_loss: Stop loss level
        targets: JSON array of target prices
        confidence: Strength score
        volume_ratio: Volume vs average
        metadata: Additional data (JSON)
        active: Whether setup is still valid
        triggered_at: Entry trigger timestamp
    """
    __tablename__ = "intraday_setups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    setup_id = Column(String(64), nullable=False, unique=True, index=True)
    setup_type = Column(String(32), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    direction = Column(String(16), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    trigger_price = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    targets = Column(Text, nullable=False)  # JSON array
    confidence = Column(Float, nullable=False)
    volume_ratio = Column(Float, nullable=False)
    metadata = Column(Text, nullable=False, default="{}")  # JSON
    active = Column(Boolean, nullable=False, default=True, index=True)
    triggered_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_setup_symbol_time", "symbol", "timestamp"),
        Index("idx_setup_active", "active", "timestamp"),
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
# Helper Functions
# ---------------------------------------------------------------------------

def _calculate_atr(candles: List[Dict], period: int = 14) -> float:
    """
    Calculate Average True Range (ATR) for volatility measurement.

    ATR = Average of True Range over last N periods
    True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
    """
    if len(candles) < period + 1:
        return 0.0

    true_ranges = []
    for i in range(1, len(candles)):
        curr = candles[i]
        prev = candles[i - 1]

        tr = max(
            curr["high"] - curr["low"],
            abs(curr["high"] - prev["close"]),
            abs(curr["low"] - prev["close"])
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return 0.0

    return np.mean(true_ranges[-period:])


def _identify_swings(candles: List[Dict], swing_window: int = 5) -> List[PriceSwing]:
    """
    Identify swing highs and lows in price data.

    Swing High: Highest high in a window of N candles on each side
    Swing Low: Lowest low in a window of N candles on each side
    """
    if len(candles) < swing_window * 2 + 1:
        return []

    swings = []

    for i in range(swing_window, len(candles) - swing_window):
        candle = candles[i]

        # Check for swing high
        is_swing_high = True
        for j in range(i - swing_window, i + swing_window + 1):
            if j != i and candles[j]["high"] >= candle["high"]:
                is_swing_high = False
                break

        if is_swing_high:
            swings.append(PriceSwing(
                price=candle["high"],
                timestamp=datetime.fromisoformat(candle["timestamp"]) if isinstance(candle["timestamp"], str) else candle["timestamp"],
                swing_type="high",
                volume=candle["volume"]
            ))

        # Check for swing low
        is_swing_low = True
        for j in range(i - swing_window, i + swing_window + 1):
            if j != i and candles[j]["low"] <= candle["low"]:
                is_swing_low = False
                break

        if is_swing_low:
            swings.append(PriceSwing(
                price=candle["low"],
                timestamp=datetime.fromisoformat(candle["timestamp"]) if isinstance(candle["timestamp"], str) else candle["timestamp"],
                swing_type="low",
                volume=candle["volume"]
            ))

    return swings


def _is_consolidation(candles: List[Dict], atr: float, price: float) -> bool:
    """
    Check if price is in consolidation (tight range).

    Consolidation criteria:
    - Range of highs/lows < ATR_THRESHOLD * ATR
    - Minimum number of candles
    """
    if len(candles) < CONSOLIDATION_MIN_CANDLES:
        return False

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    price_range = max(highs) - min(lows)
    threshold = CONSOLIDATION_ATR_THRESHOLD * atr

    return price_range < threshold and price_range > 0


def _generate_setup_id(setup_type: SetupType, symbol: str, timestamp: datetime) -> str:
    """Generate unique setup ID"""
    ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
    return f"{setup_type.value}_{symbol}_{ts_str}"


# ---------------------------------------------------------------------------
# Main Setup Detector Service
# ---------------------------------------------------------------------------

class IntradaySetupDetector:
    """
    Intraday Trading Setup Detection Service.

    Detects and validates three core intraday patterns:
    1. Opening Breakout (ORB)
    2. Retest of Support/Resistance
    3. Consolidation Breakout

    Integrates with:
    - IntradayDataService: Real-time candle data
    - SupportResistanceService: Key price levels
    - VolumeAnalyzer: Volume confirmation
    """

    def __init__(
        self,
        intraday_service=None,
        sr_service=None,
        volume_analyzer=None,
        buffer_size: int = 100
    ):
        """
        Initialize setup detector.

        Parameters:
            intraday_service: IntradayDataService instance (for live candles)
            sr_service: SupportResistanceService instance (for S/R levels)
            volume_analyzer: VolumeAnalyzer instance (for volume validation)
            buffer_size: Number of candles to retain for analysis
        """
        self.intraday_service = intraday_service
        self.sr_service = sr_service
        self.volume_analyzer = volume_analyzer
        self.buffer_size = buffer_size

        # Internal state
        self._candle_buffer: Dict[str, deque] = defaultdict(lambda: deque(maxlen=buffer_size))
        self._active_setups: Dict[str, Dict[str, SetupAlert]] = defaultdict(dict)  # symbol -> {setup_id -> SetupAlert}
        self._alert_callbacks: List[Callable] = []
        self._lock = asyncio.Lock()
        self._initialized = False
        self._engine = None

        # Opening range tracking
        self._opening_ranges: Dict[str, Dict] = {}  # symbol -> {high, low, start_time, end_time}

        # Setup detection state
        self._last_detection_time: Dict[str, datetime] = {}  # symbol -> last check time

        logger.info("IntradaySetupDetector initialized")

    async def initialize(self):
        """Initialize database and setup callback hooks"""
        if self._initialized:
            return

        try:
            # Initialize database
            self._engine = _get_db_engine()
            _SetupBase.metadata.create_all(self._engine)
            logger.info("Setup detector database initialized")

            # Load active setups from database
            await self._load_active_setups()

            # Register candle update callback if intraday service available
            if self.intraday_service:
                self.intraday_service.register_candle_callback(self._on_new_candle)
                logger.info("Registered candle callback with intraday service")

            self._initialized = True
            logger.success("IntradaySetupDetector initialization complete")

        except Exception as e:
            logger.error(f"Failed to initialize setup detector: {e}")
            raise

    def register_alert_callback(self, callback: Callable[[SetupAlert], None]):
        """
        Register callback for setup alerts.

        Callback will be invoked whenever a new setup is detected.
        Signature: callback(setup: SetupAlert) -> None
        """
        self._alert_callbacks.append(callback)
        logger.info(f"Registered setup alert callback: {callback.__name__}")

    async def _load_active_setups(self):
        """Load active setups from database on startup"""
        try:
            with Session(self._engine) as session:
                cutoff = datetime.now(_IST) - timedelta(hours=24)
                rows = session.query(_SetupAlertRow).filter(
                    _SetupAlertRow.active == True,
                    _SetupAlertRow.timestamp >= cutoff
                ).all()

                for row in rows:
                    setup = SetupAlert(
                        setup_id=row.setup_id,
                        setup_type=SetupType(row.setup_type),
                        symbol=row.symbol,
                        direction=Direction(row.direction),
                        timestamp=row.timestamp.replace(tzinfo=_IST) if row.timestamp.tzinfo is None else row.timestamp,
                        trigger_price=row.trigger_price,
                        entry_price=row.entry_price,
                        stop_loss=row.stop_loss,
                        targets=json.loads(row.targets),
                        confidence=row.confidence,
                        volume_ratio=row.volume_ratio,
                        metadata=json.loads(row.metadata),
                        active=row.active,
                        triggered_at=row.triggered_at.replace(tzinfo=_IST) if row.triggered_at and row.triggered_at.tzinfo is None else row.triggered_at
                    )
                    self._active_setups[row.symbol][row.setup_id] = setup

                logger.info(f"Loaded {len(rows)} active setups from database")

        except Exception as e:
            logger.error(f"Failed to load active setups: {e}")

    async def _on_new_candle(self, candle: Dict):
        """
        Callback for new candle data from IntradayDataService.

        Triggered on each 1-min or 5-min candle close.
        """
        try:
            symbol = candle.get("symbol")
            if not symbol:
                return

            # Add to buffer
            async with self._lock:
                self._candle_buffer[symbol].append(candle)

            # Run setup detection
            await self._detect_setups(symbol)

        except Exception as e:
            logger.error(f"Error processing new candle: {e}")

    async def _detect_setups(self, symbol: str):
        """
        Main setup detection logic.

        Runs all three pattern detectors and emits alerts.
        """
        try:
            async with self._lock:
                candles = list(self._candle_buffer[symbol])

            if len(candles) < 10:
                return  # Need minimum candles for analysis

            current_time = datetime.now(_IST)

            # Skip if recently checked (avoid redundant processing)
            last_check = self._last_detection_time.get(symbol)
            if last_check and (current_time - last_check).total_seconds() < 60:
                return

            self._last_detection_time[symbol] = current_time

            # Calculate current ATR for volatility context
            atr = _calculate_atr(candles, period=14)

            # Detect patterns (in parallel for efficiency)
            setups = []

            # 1. Opening Breakout
            orb_setup = await self._detect_opening_breakout(symbol, candles, atr)
            if orb_setup:
                setups.append(orb_setup)

            # 2. Retest
            retest_setup = await self._detect_retest(symbol, candles, atr)
            if retest_setup:
                setups.append(retest_setup)

            # 3. Consolidation Break
            consol_setup = await self._detect_consolidation_break(symbol, candles, atr)
            if consol_setup:
                setups.append(consol_setup)

            # Process and emit valid setups
            for setup in setups:
                if setup.confidence >= MIN_SETUP_CONFIDENCE:
                    await self._emit_setup_alert(setup)

        except Exception as e:
            logger.error(f"Error in setup detection for {symbol}: {e}")

    async def _detect_opening_breakout(
        self,
        symbol: str,
        candles: List[Dict],
        atr: float
    ) -> Optional[SetupAlert]:
        """
        Detect Opening Range Breakout (ORB) setup.

        Logic:
        1. Define opening range: first 15-30 minutes high/low
        2. Wait for price to break above/below with volume
        3. Validate breakout with strong close beyond range
        4. Entry: Breakout level
        5. SL: Opposite end of range
        6. Targets: R:R based (1.5:1, 2:1, 3:1)
        """
        try:
            current_time = datetime.now(_IST)
            market_open = current_time.replace(hour=9, minute=15, second=0, microsecond=0)

            # Check if we're past opening range period
            minutes_since_open = (current_time - market_open).total_seconds() / 60

            if minutes_since_open < OPENING_RANGE_DURATION_MIN:
                return None  # Too early

            # Define or retrieve opening range
            if symbol not in self._opening_ranges:
                # Calculate opening range from first N candles
                opening_candles = [
                    c for c in candles
                    if (datetime.fromisoformat(c["timestamp"]) if isinstance(c["timestamp"], str) else c["timestamp"]) < market_open + timedelta(minutes=OPENING_RANGE_MAX_DURATION)
                ]

                if len(opening_candles) < OPENING_RANGE_DURATION_MIN:
                    return None

                or_high = max(c["high"] for c in opening_candles)
                or_low = min(c["low"] for c in opening_candles)

                self._opening_ranges[symbol] = {
                    "high": or_high,
                    "low": or_low,
                    "start_time": market_open,
                    "end_time": market_open + timedelta(minutes=OPENING_RANGE_MAX_DURATION)
                }

            or_data = self._opening_ranges[symbol]
            or_high = or_data["high"]
            or_low = or_data["low"]
            or_range = or_high - or_low

            # Get current candle
            current_candle = candles[-1]
            current_price = current_candle["close"]
            current_volume = current_candle["volume"]

            # Check for breakout
            direction = None
            trigger_price = None

            if current_price > or_high and current_candle["close"] > or_high:
                # Bullish breakout
                direction = Direction.LONG
                trigger_price = or_high
            elif current_price < or_low and current_candle["close"] < or_low:
                # Bearish breakout
                direction = Direction.SHORT
                trigger_price = or_low
            else:
                return None  # No breakout

            # Volume validation
            volume_ratio = await self._get_volume_ratio(symbol, current_volume, current_time)
            if volume_ratio < VOLUME_SPIKE_THRESHOLD:
                return None  # Insufficient volume

            # Calculate entry, SL, targets
            if direction == Direction.LONG:
                entry_price = or_high + (or_range * 0.02)  # 2% buffer above breakout
                stop_loss = or_low
                risk = entry_price - stop_loss
                targets = [
                    entry_price + (risk * 1.5),
                    entry_price + (risk * 2.0),
                    entry_price + (risk * 3.0)
                ]
            else:
                entry_price = or_low - (or_range * 0.02)
                stop_loss = or_high
                risk = stop_loss - entry_price
                targets = [
                    entry_price - (risk * 1.5),
                    entry_price - (risk * 2.0),
                    entry_price - (risk * 3.0)
                ]

            # Calculate confidence score
            confidence = self._calculate_orb_confidence(
                volume_ratio=volume_ratio,
                range_size=or_range,
                atr=atr,
                time_since_open=minutes_since_open
            )

            # Create setup alert
            setup_id = _generate_setup_id(SetupType.OPENING_BREAKOUT, symbol, current_time)

            setup = SetupAlert(
                setup_id=setup_id,
                setup_type=SetupType.OPENING_BREAKOUT,
                symbol=symbol,
                direction=direction,
                timestamp=current_time,
                trigger_price=trigger_price,
                entry_price=entry_price,
                stop_loss=stop_loss,
                targets=targets,
                confidence=confidence,
                volume_ratio=volume_ratio,
                metadata={
                    "opening_range_high": or_high,
                    "opening_range_low": or_low,
                    "opening_range_size": or_range,
                    "minutes_since_open": minutes_since_open,
                    "breakout_candle_close": current_price
                }
            )

            return setup

        except Exception as e:
            logger.error(f"Error detecting opening breakout: {e}")
            return None

    async def _detect_retest(
        self,
        symbol: str,
        candles: List[Dict],
        atr: float
    ) -> Optional[SetupAlert]:
        """
        Detect Retest setup.

        Logic:
        1. Identify recent support/resistance level
        2. Detect price approaching level (within tolerance)
        3. Wait for rejection candle (strong wick, volume)
        4. Entry: After bounce confirmation
        5. SL: Below/above tested level
        6. Targets: Previous swing or 2:1 R:R
        """
        try:
            if not self.sr_service:
                return None  # Need S/R service

            # Get current S/R levels
            sr_levels = await self._get_sr_levels(symbol)
            if not sr_levels:
                return None

            # Get recent candles (last 20 for retest detection)
            recent_candles = candles[-20:] if len(candles) >= 20 else candles
            current_candle = candles[-1]
            current_price = current_candle["close"]
            current_volume = current_candle["volume"]
            current_time = datetime.now(_IST)

            # Check if price is near any S/R level
            for level in sr_levels:
                level_price = level["price"]
                level_type = level["type"]  # "support" or "resistance"

                # Calculate tolerance
                tolerance = level_price * (RETEST_TOLERANCE_PCT / 100)

                # Check if current price is testing the level
                if not (level_price - tolerance <= current_price <= level_price + tolerance):
                    continue

                # Determine direction based on level type
                if level_type == "support":
                    # Support retest = bullish setup
                    direction = Direction.LONG

                    # Check for rejection (long wick below, close near high)
                    wick_length = current_candle["low"] - min(current_candle["open"], current_candle["close"])
                    body_length = abs(current_candle["close"] - current_candle["open"])

                    if wick_length < body_length * 1.5:
                        continue  # Not a strong rejection

                    if current_candle["close"] < (current_candle["high"] - (current_candle["high"] - current_candle["low"]) * 0.3):
                        continue  # Close not near high

                    entry_price = current_candle["high"] + (atr * 0.1)
                    stop_loss = level_price - (atr * 0.5)
                    risk = entry_price - stop_loss

                    # Find previous swing high for target
                    swings = _identify_swings(recent_candles)
                    swing_highs = [s.price for s in swings if s.swing_type == "high" and s.price > current_price]
                    target_price = max(swing_highs) if swing_highs else entry_price + (risk * 2.0)

                    targets = [target_price, entry_price + (risk * 2.5), entry_price + (risk * 3.0)]

                elif level_type == "resistance":
                    # Resistance retest = bearish setup
                    direction = Direction.SHORT

                    # Check for rejection (long wick above, close near low)
                    wick_length = max(current_candle["open"], current_candle["close"]) - current_candle["high"]
                    body_length = abs(current_candle["close"] - current_candle["open"])

                    if wick_length < body_length * 1.5:
                        continue  # Not a strong rejection

                    if current_candle["close"] > (current_candle["low"] + (current_candle["high"] - current_candle["low"]) * 0.3):
                        continue  # Close not near low

                    entry_price = current_candle["low"] - (atr * 0.1)
                    stop_loss = level_price + (atr * 0.5)
                    risk = stop_loss - entry_price

                    # Find previous swing low for target
                    swings = _identify_swings(recent_candles)
                    swing_lows = [s.price for s in swings if s.swing_type == "low" and s.price < current_price]
                    target_price = min(swing_lows) if swing_lows else entry_price - (risk * 2.0)

                    targets = [target_price, entry_price - (risk * 2.5), entry_price - (risk * 3.0)]

                else:
                    continue

                # Volume validation
                volume_ratio = await self._get_volume_ratio(symbol, current_volume, current_time)
                if volume_ratio < 1.2:  # Lower threshold for retests
                    continue

                # Calculate confidence
                confidence = self._calculate_retest_confidence(
                    volume_ratio=volume_ratio,
                    level_strength=level.get("strength", 0.5),
                    wick_ratio=wick_length / body_length if body_length > 0 else 0,
                    distance_from_level=abs(current_price - level_price) / level_price
                )

                # Create setup
                setup_id = _generate_setup_id(SetupType.RETEST, symbol, current_time)

                setup = SetupAlert(
                    setup_id=setup_id,
                    setup_type=SetupType.RETEST,
                    symbol=symbol,
                    direction=direction,
                    timestamp=current_time,
                    trigger_price=level_price,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    targets=targets,
                    confidence=confidence,
                    volume_ratio=volume_ratio,
                    metadata={
                        "sr_level": level_price,
                        "level_type": level_type,
                        "level_strength": level.get("strength", 0.5),
                        "rejection_candle_close": current_price,
                        "wick_length": wick_length,
                        "body_length": body_length
                    }
                )

                return setup  # Return first valid retest found

            return None

        except Exception as e:
            logger.error(f"Error detecting retest: {e}")
            return None

    async def _detect_consolidation_break(
        self,
        symbol: str,
        candles: List[Dict],
        atr: float
    ) -> Optional[SetupAlert]:
        """
        Detect Consolidation Breakout setup.

        Logic:
        1. Identify consolidation zone (tight range, low volatility)
        2. Wait for breakout with volume expansion
        3. Validate with strong close beyond range
        4. Entry: Breakout level
        5. SL: Inside consolidation
        6. Targets: Projected move (consolidation width)
        """
        try:
            # Need minimum candles for consolidation
            if len(candles) < CONSOLIDATION_MIN_CANDLES + 10:
                return None

            current_candle = candles[-1]
            current_price = current_candle["close"]
            current_volume = current_candle["volume"]
            current_time = datetime.now(_IST)

            # Look back for consolidation zone
            lookback_candles = candles[-(CONSOLIDATION_MIN_CANDLES + 10):-1]

            # Check recent candles for consolidation
            for i in range(len(lookback_candles) - CONSOLIDATION_MIN_CANDLES):
                consol_candles = lookback_candles[i:i + CONSOLIDATION_MIN_CANDLES]

                if _is_consolidation(consol_candles, atr, current_price):
                    # Found consolidation zone
                    consol_high = max(c["high"] for c in consol_candles)
                    consol_low = min(c["low"] for c in consol_candles)
                    consol_range = consol_high - consol_low

                    # Check for breakout
                    direction = None
                    trigger_price = None

                    if current_price > consol_high and current_candle["close"] > consol_high:
                        # Bullish breakout
                        direction = Direction.LONG
                        trigger_price = consol_high
                    elif current_price < consol_low and current_candle["close"] < consol_low:
                        # Bearish breakout
                        direction = Direction.SHORT
                        trigger_price = consol_low
                    else:
                        continue  # No breakout yet

                    # Volume validation
                    volume_ratio = await self._get_volume_ratio(symbol, current_volume, current_time)
                    if volume_ratio < VOLUME_SPIKE_THRESHOLD:
                        continue

                    # Calculate entry, SL, targets
                    if direction == Direction.LONG:
                        entry_price = consol_high + (consol_range * 0.02)
                        stop_loss = consol_low
                        risk = entry_price - stop_loss

                        # Projected move = consolidation range
                        projection = consol_range
                        targets = [
                            entry_price + projection,
                            entry_price + (projection * 1.5),
                            entry_price + (projection * 2.0)
                        ]
                    else:
                        entry_price = consol_low - (consol_range * 0.02)
                        stop_loss = consol_high
                        risk = stop_loss - entry_price

                        projection = consol_range
                        targets = [
                            entry_price - projection,
                            entry_price - (projection * 1.5),
                            entry_price - (projection * 2.0)
                        ]

                    # Calculate confidence
                    confidence = self._calculate_consolidation_confidence(
                        volume_ratio=volume_ratio,
                        consol_duration=len(consol_candles),
                        range_tightness=consol_range / atr if atr > 0 else 0,
                        breakout_strength=(current_price - trigger_price) / consol_range if consol_range > 0 else 0
                    )

                    # Create setup
                    setup_id = _generate_setup_id(SetupType.CONSOLIDATION_BREAK, symbol, current_time)

                    setup = SetupAlert(
                        setup_id=setup_id,
                        setup_type=SetupType.CONSOLIDATION_BREAK,
                        symbol=symbol,
                        direction=direction,
                        timestamp=current_time,
                        trigger_price=trigger_price,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        targets=targets,
                        confidence=confidence,
                        volume_ratio=volume_ratio,
                        metadata={
                            "consolidation_high": consol_high,
                            "consolidation_low": consol_low,
                            "consolidation_range": consol_range,
                            "consolidation_duration": len(consol_candles),
                            "breakout_candle_close": current_price,
                            "range_atr_ratio": consol_range / atr if atr > 0 else 0
                        }
                    )

                    return setup

            return None

        except Exception as e:
            logger.error(f"Error detecting consolidation break: {e}")
            return None

    def _calculate_orb_confidence(
        self,
        volume_ratio: float,
        range_size: float,
        atr: float,
        time_since_open: float
    ) -> float:
        """Calculate confidence score for Opening Range Breakout"""
        score = 0.0

        # Volume component (0-0.35)
        if volume_ratio >= 2.5:
            score += 0.35
        elif volume_ratio >= 2.0:
            score += 0.30
        elif volume_ratio >= 1.5:
            score += 0.20
        else:
            score += 0.10

        # Range size component (0-0.25)
        if atr > 0:
            range_ratio = range_size / atr
            if 0.5 <= range_ratio <= 1.5:
                score += 0.25  # Ideal range
            elif 0.3 <= range_ratio < 0.5 or 1.5 < range_ratio <= 2.0:
                score += 0.15
            else:
                score += 0.05

        # Timing component (0-0.25)
        if 20 <= time_since_open <= 45:
            score += 0.25  # Ideal breakout timing
        elif 15 <= time_since_open < 20 or 45 < time_since_open <= 60:
            score += 0.15
        else:
            score += 0.05

        # Base confidence (0-0.15)
        score += 0.15

        return min(1.0, score)

    def _calculate_retest_confidence(
        self,
        volume_ratio: float,
        level_strength: float,
        wick_ratio: float,
        distance_from_level: float
    ) -> float:
        """Calculate confidence score for Retest setup"""
        score = 0.0

        # Level strength component (0-0.30)
        score += level_strength * 0.30

        # Volume component (0-0.25)
        if volume_ratio >= 1.5:
            score += 0.25
        elif volume_ratio >= 1.2:
            score += 0.15
        else:
            score += 0.05

        # Rejection quality (wick ratio) (0-0.25)
        if wick_ratio >= 3.0:
            score += 0.25
        elif wick_ratio >= 2.0:
            score += 0.20
        elif wick_ratio >= 1.5:
            score += 0.15
        else:
            score += 0.05

        # Proximity to level (0-0.20)
        if distance_from_level <= 0.001:  # Within 0.1%
            score += 0.20
        elif distance_from_level <= 0.003:  # Within 0.3%
            score += 0.15
        else:
            score += 0.05

        return min(1.0, score)

    def _calculate_consolidation_confidence(
        self,
        volume_ratio: float,
        consol_duration: int,
        range_tightness: float,
        breakout_strength: float
    ) -> float:
        """Calculate confidence score for Consolidation Break"""
        score = 0.0

        # Volume component (0-0.35)
        if volume_ratio >= 2.5:
            score += 0.35
        elif volume_ratio >= 2.0:
            score += 0.25
        elif volume_ratio >= 1.5:
            score += 0.15
        else:
            score += 0.05

        # Consolidation duration (0-0.25)
        if 15 <= consol_duration <= 30:
            score += 0.25
        elif 10 <= consol_duration < 15 or 30 < consol_duration <= 40:
            score += 0.15
        else:
            score += 0.05

        # Range tightness (0-0.20)
        if range_tightness <= 0.3:
            score += 0.20  # Very tight
        elif range_tightness <= 0.5:
            score += 0.15
        else:
            score += 0.05

        # Breakout strength (0-0.20)
        if abs(breakout_strength) >= 0.5:
            score += 0.20
        elif abs(breakout_strength) >= 0.3:
            score += 0.15
        else:
            score += 0.10

        return min(1.0, score)

    async def _get_volume_ratio(self, symbol: str, current_volume: int, timestamp: datetime) -> float:
        """Get volume ratio (current vs average) from VolumeAnalyzer"""
        try:
            if not self.volume_analyzer:
                return 1.5  # Default if analyzer not available

            time_slot = timestamp.strftime("%H:%M")
            avg_volume = await self.volume_analyzer.get_slot_average(symbol, time_slot)

            if avg_volume > 0:
                return current_volume / avg_volume
            return 1.5

        except Exception as e:
            logger.error(f"Error getting volume ratio: {e}")
            return 1.5

    async def _get_sr_levels(self, symbol: str) -> List[Dict]:
        """Get current S/R levels from SupportResistanceService"""
        try:
            if not self.sr_service:
                return []

            # Get levels from service (method signature may vary)
            levels = await self.sr_service.get_levels(symbol)
            return levels if levels else []

        except Exception as e:
            logger.error(f"Error getting S/R levels: {e}")
            return []

    async def _emit_setup_alert(self, setup: SetupAlert):
        """
        Emit setup alert: save to database and trigger callbacks.
        """
        try:
            # Check for duplicate (avoid re-alerting same setup)
            if setup.setup_id in self._active_setups.get(setup.symbol, {}):
                return  # Already alerted

            # Save to database
            await self._save_setup(setup)

            # Add to active setups
            async with self._lock:
                self._active_setups[setup.symbol][setup.setup_id] = setup

            # Trigger callbacks
            for callback in self._alert_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(setup)
                    else:
                        callback(setup)
                except Exception as e:
                    logger.error(f"Error in alert callback {callback.__name__}: {e}")

            logger.success(
                f"Setup Alert: {setup.setup_type.value.upper()} | {setup.symbol} | "
                f"{setup.direction.value.upper()} | Entry: {setup.entry_price:.2f} | "
                f"SL: {setup.stop_loss:.2f} | Confidence: {setup.confidence:.2%}"
            )

        except Exception as e:
            logger.error(f"Error emitting setup alert: {e}")

    async def _save_setup(self, setup: SetupAlert):
        """Save setup to database"""
        try:
            with Session(self._engine) as session:
                row = _SetupAlertRow(
                    setup_id=setup.setup_id,
                    setup_type=setup.setup_type.value,
                    symbol=setup.symbol,
                    direction=setup.direction.value,
                    timestamp=setup.timestamp,
                    trigger_price=setup.trigger_price,
                    entry_price=setup.entry_price,
                    stop_loss=setup.stop_loss,
                    targets=json.dumps(setup.targets),
                    confidence=setup.confidence,
                    volume_ratio=setup.volume_ratio,
                    metadata=json.dumps(setup.metadata),
                    active=setup.active,
                    triggered_at=setup.triggered_at
                )
                session.add(row)
                session.commit()

        except Exception as e:
            logger.error(f"Error saving setup to database: {e}")

    async def get_active_setups(self, symbol: Optional[str] = None) -> List[SetupAlert]:
        """
        Get currently active setups.

        Parameters:
            symbol: Filter by symbol (optional)

        Returns:
            List of active SetupAlert objects
        """
        async with self._lock:
            if symbol:
                return list(self._active_setups.get(symbol, {}).values())
            else:
                all_setups = []
                for setups_dict in self._active_setups.values():
                    all_setups.extend(setups_dict.values())
                return all_setups

    async def invalidate_setup(self, setup_id: str):
        """Mark setup as inactive (e.g., when conditions no longer valid)"""
        try:
            # Update in memory
            for symbol, setups in self._active_setups.items():
                if setup_id in setups:
                    setups[setup_id].active = False

                    # Update in database
                    with Session(self._engine) as session:
                        row = session.query(_SetupAlertRow).filter(
                            _SetupAlertRow.setup_id == setup_id
                        ).first()
                        if row:
                            row.active = False
                            session.commit()

                    logger.info(f"Invalidated setup: {setup_id}")
                    return

        except Exception as e:
            logger.error(f"Error invalidating setup {setup_id}: {e}")

    async def cleanup_expired_setups(self):
        """Remove setups that have expired (older than SETUP_EXPIRY_MINUTES)"""
        try:
            current_time = datetime.now(_IST)
            expired_ids = []

            async with self._lock:
                for symbol, setups in self._active_setups.items():
                    for setup_id, setup in list(setups.items()):
                        age_minutes = (current_time - setup.timestamp).total_seconds() / 60
                        if age_minutes > SETUP_EXPIRY_MINUTES:
                            expired_ids.append((symbol, setup_id))

            # Remove expired setups
            for symbol, setup_id in expired_ids:
                await self.invalidate_setup(setup_id)

            if expired_ids:
                logger.info(f"Cleaned up {len(expired_ids)} expired setups")

        except Exception as e:
            logger.error(f"Error cleaning up expired setups: {e}")
