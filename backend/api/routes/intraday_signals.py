"""
intraday_signals.py
===================
FastAPI routes for intraday trading signals and market status.

Provides real-time support/resistance levels, live trade setups,
and market status checks for intraday trading operations.

Endpoints:
- GET  /api/intraday/levels           — Fetch current S/R levels for symbols
- GET  /api/intraday/setups/live      — Stream active trade setups (SSE)
- GET  /api/intraday/market-status    — Check if within trading windows
- GET  /api/intraday/candles          — Get recent candle data
- POST /api/intraday/validate-entry   — Validate trade entry against levels
"""

import asyncio
from datetime import datetime, time, timezone, timedelta
from typing import List, Optional, Dict, Any
from enum import Enum

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
from loguru import logger

from backend.dependencies import get_sr_service, get_angel_client
from backend.services.intraday_data_service import (
    IntradayDataService,
    SYMBOL_NIFTY,
    SYMBOL_BANKNIFTY,
)
from backend.config import config, DEMO_MODE


# ---------------------------------------------------------------------------
# Router Setup
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/intraday", tags=["Intraday Signals"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

# Market timing (IST)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
PRE_MARKET_START = time(9, 0)
POST_MARKET_END = time(15, 45)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MarketPhase(str, Enum):
    """Current market phase/session."""
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    CLOSING = "closing"
    CLOSED = "closed"
    WEEKEND = "weekend"


class SetupType(str, Enum):
    """Trade setup classification."""
    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    SUPPORT_BOUNCE = "support_bounce"
    RESISTANCE_REJECTION = "resistance_rejection"
    RANGE_BOUND = "range_bound"


class SignalStrength(str, Enum):
    """Signal confidence level."""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class SRLevel(BaseModel):
    """Support or Resistance level."""
    price: float = Field(..., description="Level price")
    strength: float = Field(..., ge=0.0, le=1.0, description="Confidence 0-1")
    touches: int = Field(..., ge=0, description="Number of price touches")
    last_touch: str = Field(..., description="ISO timestamp of last touch")
    distance_pct: float = Field(..., description="% distance from current price")


class IntradayLevelsResponse(BaseModel):
    """Complete S/R levels for intraday trading."""
    symbol: str
    current_price: float
    support_levels: List[SRLevel] = Field(default_factory=list)
    resistance_levels: List[SRLevel] = Field(default_factory=list)
    pivot_points: Dict[str, float] = Field(default_factory=dict)
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    range_low: Optional[float] = None
    range_high: Optional[float] = None
    calculated_at: str
    data_source: str = "live"

    @validator("calculated_at", pre=True)
    def format_timestamp(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class TradeSetup(BaseModel):
    """Active trade setup with entry/exit levels."""
    setup_id: str
    symbol: str
    setup_type: SetupType
    signal_strength: SignalStrength
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: Optional[float] = None
    target_3: Optional[float] = None
    risk_reward: float
    timeframe: str = "5min"
    confidence: float = Field(..., ge=0.0, le=100.0)
    triggered_at: str
    expires_at: Optional[str] = None
    notes: Optional[str] = None

    @validator("triggered_at", "expires_at", pre=True)
    def format_timestamp(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class LiveSetupsResponse(BaseModel):
    """Collection of active trade setups."""
    setups: List[TradeSetup] = Field(default_factory=list)
    count: int
    last_updated: str
    market_phase: MarketPhase

    @validator("last_updated", pre=True)
    def format_timestamp(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class MarketStatusResponse(BaseModel):
    """Current market status and timing."""
    is_open: bool
    market_phase: MarketPhase
    current_time: str
    time_zone: str = "Asia/Kolkata"
    next_open: Optional[str] = None
    next_close: Optional[str] = None
    minutes_to_open: Optional[int] = None
    minutes_to_close: Optional[int] = None
    is_trading_hours: bool

    @validator("current_time", "next_open", "next_close", pre=True)
    def format_timestamp(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class CandleData(BaseModel):
    """OHLCV candle data."""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    tick_count: int = 0

    @validator("timestamp", pre=True)
    def format_timestamp(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class CandlesResponse(BaseModel):
    """Historical candle data response."""
    symbol: str
    interval: str
    candles: List[CandleData] = Field(default_factory=list)
    count: int
    from_time: str
    to_time: str

    @validator("from_time", "to_time", pre=True)
    def format_timestamp(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v


class ValidateEntryRequest(BaseModel):
    """Request to validate trade entry."""
    symbol: str = Field(..., description="Trading symbol")
    entry_price: float = Field(..., gt=0, description="Proposed entry price")
    direction: str = Field(..., description="Trade direction: LONG or SHORT")
    tolerance_pct: float = Field(default=0.2, ge=0, le=5.0, description="% tolerance for level proximity")

    @validator("direction")
    def validate_direction(cls, v):
        if v.upper() not in ["LONG", "SHORT", "BUY", "SELL"]:
            raise ValueError("direction must be LONG, SHORT, BUY, or SELL")
        return v.upper()


class ValidateEntryResponse(BaseModel):
    """Entry validation result."""
    is_valid: bool
    validation_score: float = Field(..., ge=0.0, le=100.0)
    at_support: bool = False
    at_resistance: bool = False
    nearest_level: Optional[float] = None
    level_type: Optional[str] = None
    distance_from_level: float
    risk_assessment: str
    warnings: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Service Dependency
# ---------------------------------------------------------------------------

_intraday_service: Optional[IntradayDataService] = None


def get_intraday_service() -> Optional[IntradayDataService]:
    """Get or initialize intraday data service singleton."""
    global _intraday_service

    if DEMO_MODE:
        return None

    if _intraday_service is None:
        try:
            client = get_angel_client()
            if client is not None:
                _intraday_service = IntradayDataService(
                    client=client,
                    candle_buffer_size=500,
                )
                # Start service in background
                # Note: Actual startup should be managed by app lifespan
                logger.info("Intraday data service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize intraday service: {e}")
            _intraday_service = None

    return _intraday_service


# ---------------------------------------------------------------------------
# Market Status Helpers
# ---------------------------------------------------------------------------

def get_market_phase(now: datetime) -> MarketPhase:
    """
    Determine current market phase based on IST time.

    Parameters
    ----------
    now : datetime
        Current datetime (IST-aware)

    Returns
    -------
    MarketPhase
        Current market phase
    """
    # Convert to IST if not already
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    elif now.tzinfo != IST:
        now = now.astimezone(IST)

    current_time = now.time()
    weekday = now.weekday()

    # Weekend check (Saturday=5, Sunday=6)
    if weekday >= 5:
        return MarketPhase.WEEKEND

    # Market phases
    if current_time < PRE_MARKET_START:
        return MarketPhase.CLOSED
    elif PRE_MARKET_START <= current_time < MARKET_OPEN:
        return MarketPhase.PRE_MARKET
    elif MARKET_OPEN <= current_time < time(15, 15):
        return MarketPhase.REGULAR
    elif time(15, 15) <= current_time < MARKET_CLOSE:
        return MarketPhase.CLOSING
    elif MARKET_CLOSE <= current_time < POST_MARKET_END:
        return MarketPhase.CLOSED
    else:
        return MarketPhase.CLOSED


def calculate_next_session_times(now: datetime) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Calculate next market open and close times.

    Parameters
    ----------
    now : datetime
        Current datetime (IST-aware)

    Returns
    -------
    tuple[Optional[datetime], Optional[datetime]]
        (next_open, next_close) or (None, None) if weekend
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    elif now.tzinfo != IST:
        now = now.astimezone(IST)

    phase = get_market_phase(now)

    if phase == MarketPhase.WEEKEND:
        # Calculate next Monday
        days_until_monday = (7 - now.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 1
        next_monday = now + timedelta(days=days_until_monday)
        next_open = datetime.combine(next_monday.date(), MARKET_OPEN, tzinfo=IST)
        next_close = datetime.combine(next_monday.date(), MARKET_CLOSE, tzinfo=IST)
        return next_open, next_close

    elif phase in [MarketPhase.CLOSED, MarketPhase.PRE_MARKET]:
        # Next open is today
        next_open = datetime.combine(now.date(), MARKET_OPEN, tzinfo=IST)
        if now.time() >= MARKET_OPEN:
            # Already past today's open, get tomorrow
            tomorrow = now + timedelta(days=1)
            # Skip weekend
            if tomorrow.weekday() >= 5:
                days_to_add = 7 - tomorrow.weekday()
                tomorrow = tomorrow + timedelta(days=days_to_add)
            next_open = datetime.combine(tomorrow.date(), MARKET_OPEN, tzinfo=IST)
        next_close = datetime.combine(next_open.date(), MARKET_CLOSE, tzinfo=IST)
        return next_open, next_close

    elif phase in [MarketPhase.REGULAR, MarketPhase.CLOSING]:
        # Market is open, next close is today
        next_close = datetime.combine(now.date(), MARKET_CLOSE, tzinfo=IST)
        # Next open is tomorrow (or Monday if Friday)
        tomorrow = now + timedelta(days=1)
        if tomorrow.weekday() >= 5:
            days_to_add = 7 - tomorrow.weekday()
            tomorrow = tomorrow + timedelta(days=days_to_add)
        next_open = datetime.combine(tomorrow.date(), MARKET_OPEN, tzinfo=IST)
        return next_open, next_close

    return None, None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/levels", response_model=IntradayLevelsResponse)
async def get_intraday_levels(
    symbol: str = Query(
        default=SYMBOL_NIFTY,
        description="Symbol to fetch levels for",
        regex=f"^({SYMBOL_NIFTY}|{SYMBOL_BANKNIFTY})$",
    ),
    include_pivots: bool = Query(default=True, description="Include pivot points"),
):
    """
    Fetch current support/resistance levels for intraday trading.

    Returns real-time S/R levels, pivot points, and range boundaries
    for the specified symbol. Levels are sorted by proximity to current price.

    **Symbols:**
    - `NIFTY` — Nifty 50 Index
    - `BANKNIFTY` — Bank Nifty Index

    **Response:**
    - Support/resistance levels with strength scores
    - Nearest support/resistance prices
    - Intraday pivot points (PP, R1, R2, R3, S1, S2, S3)
    - Current price and calculation timestamp

    **Example:**
    ```
    GET /api/intraday/levels?symbol=NIFTY&include_pivots=true
    ```
    """
    try:
        if DEMO_MODE:
            # Return mock data for demo mode
            return IntradayLevelsResponse(
                symbol=symbol,
                current_price=24567.85,
                support_levels=[
                    SRLevel(
                        price=24500.0,
                        strength=0.85,
                        touches=5,
                        last_touch="2026-07-15T10:30:00+05:30",
                        distance_pct=-0.28,
                    ),
                    SRLevel(
                        price=24450.0,
                        strength=0.72,
                        touches=3,
                        last_touch="2026-07-15T09:45:00+05:30",
                        distance_pct=-0.48,
                    ),
                ],
                resistance_levels=[
                    SRLevel(
                        price=24600.0,
                        strength=0.90,
                        touches=7,
                        last_touch="2026-07-15T11:15:00+05:30",
                        distance_pct=0.13,
                    ),
                    SRLevel(
                        price=24650.0,
                        strength=0.78,
                        touches=4,
                        last_touch="2026-07-15T10:00:00+05:30",
                        distance_pct=0.33,
                    ),
                ],
                pivot_points={
                    "PP": 24550.0,
                    "R1": 24620.0,
                    "R2": 24680.0,
                    "R3": 24750.0,
                    "S1": 24490.0,
                    "S2": 24420.0,
                    "S3": 24360.0,
                },
                nearest_support=24500.0,
                nearest_resistance=24600.0,
                range_low=24450.0,
                range_high=24650.0,
                calculated_at=datetime.now(IST).isoformat(),
                data_source="demo",
            )

        # Get S/R service
        sr_service = get_sr_service()
        if sr_service is None:
            raise HTTPException(
                status_code=503,
                detail="Support/Resistance service not available",
            )

        # Fetch levels from service
        levels_data = sr_service.get_levels(symbol)
        if levels_data is None:
            raise HTTPException(
                status_code=404,
                detail=f"No S/R levels found for {symbol}",
            )

        # Get current price from intraday service or fallback
        current_price = levels_data.get("current_price", 0.0)
        intraday_svc = get_intraday_service()
        if intraday_svc is not None:
            try:
                # Try to get latest tick price
                latest_candle = intraday_svc.get_latest_candle(symbol, "1min")
                if latest_candle:
                    current_price = latest_candle.close
            except Exception as e:
                logger.warning(f"Could not fetch live price: {e}")

        # Calculate distance percentages
        def calc_distance(level_price: float) -> float:
            if current_price == 0:
                return 0.0
            return ((level_price - current_price) / current_price) * 100

        # Parse support levels
        support_levels = [
            SRLevel(
                price=lvl["price"],
                strength=lvl["strength"],
                touches=lvl["touches"],
                last_touch=lvl["last_touch"],
                distance_pct=calc_distance(lvl["price"]),
            )
            for lvl in levels_data.get("support_levels", [])
        ]

        # Parse resistance levels
        resistance_levels = [
            SRLevel(
                price=lvl["price"],
                strength=lvl["strength"],
                touches=lvl["touches"],
                last_touch=lvl["last_touch"],
                distance_pct=calc_distance(lvl["price"]),
            )
            for lvl in levels_data.get("resistance_levels", [])
        ]

        # Sort by proximity to current price
        support_levels.sort(key=lambda x: abs(x.distance_pct))
        resistance_levels.sort(key=lambda x: abs(x.distance_pct))

        # Find nearest levels
        nearest_support = support_levels[0].price if support_levels else None
        nearest_resistance = resistance_levels[0].price if resistance_levels else None

        # Range boundaries (strongest levels)
        range_low = min((lvl.price for lvl in support_levels if lvl.strength > 0.7), default=None)
        range_high = max((lvl.price for lvl in resistance_levels if lvl.strength > 0.7), default=None)

        return IntradayLevelsResponse(
            symbol=symbol,
            current_price=current_price,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            pivot_points=levels_data.get("pivot_points", {}) if include_pivots else {},
            nearest_support=nearest_support,
            nearest_resistance=nearest_resistance,
            range_low=range_low,
            range_high=range_high,
            calculated_at=levels_data.get("calculated_at", datetime.now(IST).isoformat()),
            data_source="live",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching intraday levels: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch intraday levels: {str(e)}",
        )


@router.get("/setups/live", response_model=LiveSetupsResponse)
async def get_live_setups(
    symbol: Optional[str] = Query(
        default=None,
        description="Filter by symbol (optional)",
    ),
    min_confidence: float = Query(
        default=60.0,
        ge=0.0,
        le=100.0,
        description="Minimum confidence threshold",
    ),
):
    """
    Get currently active trade setups.

    Returns trade setups that are currently valid based on:
    - Price action near S/R levels
    - Volume confirmation
    - Trend alignment
    - Risk/reward ratio

    **Parameters:**
    - `symbol`: Filter by specific symbol (optional)
    - `min_confidence`: Minimum confidence score (0-100)

    **Setup Types:**
    - `breakout`: Price breaking above resistance
    - `breakdown`: Price breaking below support
    - `support_bounce`: Bounce from support level
    - `resistance_rejection`: Rejection at resistance
    - `range_bound`: Trading within defined range

    **Example:**
    ```
    GET /api/intraday/setups/live?symbol=NIFTY&min_confidence=70
    ```
    """
    try:
        now = datetime.now(IST)
        phase = get_market_phase(now)

        if DEMO_MODE or phase not in [MarketPhase.REGULAR, MarketPhase.CLOSING]:
            # Return demo/empty data
            return LiveSetupsResponse(
                setups=[],
                count=0,
                last_updated=now.isoformat(),
                market_phase=phase,
            )

        # TODO: Implement actual setup detection logic
        # This would analyze current price action against S/R levels,
        # volume patterns, and trend indicators to identify valid setups

        setups = []

        # Placeholder: Generate sample setup when market is open
        if symbol is None or symbol == SYMBOL_NIFTY:
            setups.append(
                TradeSetup(
                    setup_id=f"NIFTY_{now.timestamp()}",
                    symbol=SYMBOL_NIFTY,
                    setup_type=SetupType.SUPPORT_BOUNCE,
                    signal_strength=SignalStrength.MODERATE,
                    entry_price=24520.0,
                    stop_loss=24480.0,
                    target_1=24580.0,
                    target_2=24620.0,
                    target_3=24650.0,
                    risk_reward=2.5,
                    timeframe="5min",
                    confidence=72.5,
                    triggered_at=now.isoformat(),
                    expires_at=(now + timedelta(minutes=30)).isoformat(),
                    notes="Strong support bounce with volume confirmation",
                )
            )

        # Filter by confidence
        setups = [s for s in setups if s.confidence >= min_confidence]

        return LiveSetupsResponse(
            setups=setups,
            count=len(setups),
            last_updated=now.isoformat(),
            market_phase=phase,
        )

    except Exception as e:
        logger.error(f"Error fetching live setups: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch live setups: {str(e)}",
        )


@router.get("/market-status", response_model=MarketStatusResponse)
async def get_market_status():
    """
    Check current market status and trading windows.

    Returns detailed market timing information including:
    - Current market phase (pre-market, regular, closing, closed, weekend)
    - Whether market is open for trading
    - Time until next open/close
    - Current IST time

    **Market Phases:**
    - `pre_market`: 09:00 - 09:15 IST
    - `regular`: 09:15 - 15:15 IST (main trading session)
    - `closing`: 15:15 - 15:30 IST (final 15 minutes)
    - `closed`: Outside market hours
    - `weekend`: Saturday/Sunday

    **Example:**
    ```
    GET /api/intraday/market-status
    ```
    """
    try:
        now = datetime.now(IST)
        phase = get_market_phase(now)

        # Determine if trading is allowed
        is_trading_hours = phase in [MarketPhase.REGULAR, MarketPhase.CLOSING]
        is_open = phase in [MarketPhase.PRE_MARKET, MarketPhase.REGULAR, MarketPhase.CLOSING]

        # Calculate next session times
        next_open, next_close = calculate_next_session_times(now)

        # Calculate minutes to open/close
        minutes_to_open = None
        minutes_to_close = None

        if next_open and phase != MarketPhase.REGULAR:
            minutes_to_open = int((next_open - now).total_seconds() / 60)

        if next_close and is_trading_hours:
            minutes_to_close = int((next_close - now).total_seconds() / 60)

        return MarketStatusResponse(
            is_open=is_open,
            market_phase=phase,
            current_time=now.isoformat(),
            time_zone="Asia/Kolkata",
            next_open=next_open.isoformat() if next_open else None,
            next_close=next_close.isoformat() if next_close else None,
            minutes_to_open=minutes_to_open,
            minutes_to_close=minutes_to_close,
            is_trading_hours=is_trading_hours,
        )

    except Exception as e:
        logger.error(f"Error checking market status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check market status: {str(e)}",
        )


@router.get("/candles", response_model=CandlesResponse)
async def get_recent_candles(
    symbol: str = Query(
        default=SYMBOL_NIFTY,
        description="Symbol to fetch candles for",
        regex=f"^({SYMBOL_NIFTY}|{SYMBOL_BANKNIFTY})$",
    ),
    interval: str = Query(
        default="5min",
        description="Candle interval",
        regex="^(1min|5min)$",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=500,
        description="Number of candles to fetch",
    ),
):
    """
    Get recent candle data for charting and analysis.

    Returns OHLCV candle data for the specified symbol and interval.
    Candles are sorted from oldest to newest.

    **Parameters:**
    - `symbol`: Trading symbol (NIFTY or BANKNIFTY)
    - `interval`: Candle timeframe (1min or 5min)
    - `limit`: Number of candles (1-500)

    **Example:**
    ```
    GET /api/intraday/candles?symbol=NIFTY&interval=5min&limit=100
    ```
    """
    try:
        if DEMO_MODE:
            # Return mock candles
            now = datetime.now(IST)
            candles = []
            for i in range(limit):
                ts = now - timedelta(minutes=(limit - i) * (5 if interval == "5min" else 1))
                candles.append(
                    CandleData(
                        timestamp=ts.isoformat(),
                        open=24500.0 + (i % 10) * 5,
                        high=24510.0 + (i % 10) * 5,
                        low=24490.0 + (i % 10) * 5,
                        close=24505.0 + (i % 10) * 5,
                        volume=100000 + (i % 100) * 1000,
                        tick_count=50,
                    )
                )

            return CandlesResponse(
                symbol=symbol,
                interval=interval,
                candles=candles,
                count=len(candles),
                from_time=candles[0].timestamp if candles else now.isoformat(),
                to_time=candles[-1].timestamp if candles else now.isoformat(),
            )

        # Get intraday service
        intraday_svc = get_intraday_service()
        if intraday_svc is None:
            raise HTTPException(
                status_code=503,
                detail="Intraday data service not available",
            )

        # Fetch candles
        candles_raw = intraday_svc.get_candles(symbol, interval, limit)

        if not candles_raw:
            raise HTTPException(
                status_code=404,
                detail=f"No candle data available for {symbol} ({interval})",
            )

        # Convert to response format
        candles = [
            CandleData(
                timestamp=c.timestamp.isoformat(),
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                tick_count=c.tick_count,
            )
            for c in candles_raw
        ]

        return CandlesResponse(
            symbol=symbol,
            interval=interval,
            candles=candles,
            count=len(candles),
            from_time=candles[0].timestamp if candles else datetime.now(IST).isoformat(),
            to_time=candles[-1].timestamp if candles else datetime.now(IST).isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching candles: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch candles: {str(e)}",
        )


@router.post("/validate-entry", response_model=ValidateEntryResponse)
async def validate_trade_entry(request: ValidateEntryRequest):
    """
    Validate a proposed trade entry against current S/R levels.

    Checks if the entry price aligns with support/resistance levels,
    assesses risk, and provides warnings/suggestions for optimization.

    **Request Body:**
    ```json
    {
        "symbol": "NIFTY",
        "entry_price": 24520.0,
        "direction": "LONG",
        "tolerance_pct": 0.2
    }
    ```

    **Response:**
    - `is_valid`: Whether entry meets validation criteria
    - `validation_score`: Overall score 0-100
    - `at_support/at_resistance`: Proximity to key levels
    - `risk_assessment`: Risk evaluation (LOW, MODERATE, HIGH)
    - `warnings`: Issues to be aware of
    - `suggestions`: Optimization recommendations

    **Example:**
    ```
    POST /api/intraday/validate-entry
    ```
    """
    try:
        # Get S/R service
        sr_service = get_sr_service()
        if sr_service is None and not DEMO_MODE:
            raise HTTPException(
                status_code=503,
                detail="Validation service not available",
            )

        warnings = []
        suggestions = []
        at_support = False
        at_resistance = False
        nearest_level = None
        level_type = None
        distance_from_level = float('inf')

        if DEMO_MODE:
            # Mock validation
            nearest_level = 24500.0
            distance_from_level = abs(request.entry_price - nearest_level)
            distance_pct = (distance_from_level / nearest_level) * 100

            if distance_pct <= request.tolerance_pct:
                at_support = request.direction in ["LONG", "BUY"]
                at_resistance = request.direction in ["SHORT", "SELL"]
                level_type = "support" if at_support else "resistance"

            validation_score = max(0, 100 - (distance_pct * 10))

        else:
            # Real validation logic
            levels_data = sr_service.get_levels(request.symbol)

            if not levels_data:
                warnings.append(f"No S/R data available for {request.symbol}")
                validation_score = 50.0
            else:
                all_levels = []
                all_levels.extend([(lvl["price"], "support") for lvl in levels_data.get("support_levels", [])])
                all_levels.extend([(lvl["price"], "resistance") for lvl in levels_data.get("resistance_levels", [])])

                # Find nearest level
                for price, ltype in all_levels:
                    dist = abs(request.entry_price - price)
                    if dist < distance_from_level:
                        distance_from_level = dist
                        nearest_level = price
                        level_type = ltype

                # Check if within tolerance
                if nearest_level:
                    distance_pct = (distance_from_level / nearest_level) * 100

                    if distance_pct <= request.tolerance_pct:
                        if level_type == "support":
                            at_support = True
                            if request.direction not in ["LONG", "BUY"]:
                                warnings.append("Shorting at support - high risk of reversal")
                        else:
                            at_resistance = True
                            if request.direction not in ["SHORT", "SELL"]:
                                warnings.append("Buying at resistance - high risk of rejection")

                    # Calculate validation score
                    alignment_bonus = 20 if (
                        (at_support and request.direction in ["LONG", "BUY"]) or
                        (at_resistance and request.direction in ["SHORT", "SELL"])
                    ) else 0

                    proximity_score = max(0, 80 - (distance_pct * 40))
                    validation_score = min(100, proximity_score + alignment_bonus)
                else:
                    validation_score = 30.0
                    warnings.append("No nearby S/R levels - trading in no-man's land")

        # Risk assessment
        if validation_score >= 75:
            risk_assessment = "LOW"
        elif validation_score >= 50:
            risk_assessment = "MODERATE"
            suggestions.append("Consider waiting for better level alignment")
        else:
            risk_assessment = "HIGH"
            suggestions.append("Entry not aligned with key levels - reconsider")
            if nearest_level:
                suggestions.append(f"Consider entry near {nearest_level:.2f} instead")

        # Additional suggestions
        if not at_support and not at_resistance:
            suggestions.append("Wait for price to reach a defined S/R level")

        is_valid = validation_score >= 60 and len([w for w in warnings if "high risk" in w.lower()]) == 0

        return ValidateEntryResponse(
            is_valid=is_valid,
            validation_score=validation_score,
            at_support=at_support,
            at_resistance=at_resistance,
            nearest_level=nearest_level,
            level_type=level_type,
            distance_from_level=distance_from_level,
            risk_assessment=risk_assessment,
            warnings=warnings,
            suggestions=suggestions,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating entry: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to validate entry: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

@router.exception_handler(ValueError)
async def value_error_handler(request, exc):
    """Handle validation errors."""
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )


@router.exception_handler(Exception)
async def general_error_handler(request, exc):
    """Handle unexpected errors."""
    logger.error(f"Unexpected error in intraday routes: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
