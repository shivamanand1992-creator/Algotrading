"""
support_resistance.py
=====================
REST API endpoints for Support/Resistance levels.

Endpoints:
- GET  /api/sr/levels/{symbol}  — Get current S/R levels for a symbol
- POST /api/sr/refresh          — Manually trigger refresh for symbols
- GET  /api/sr/validate         — Check if price is at a known S/R level
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.dependencies import get_sr_service
from loguru import logger

router = APIRouter(prefix="/api/sr", tags=["Support/Resistance"])


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class SRLevel(BaseModel):
    """Single support or resistance level."""
    price: float
    strength: float  # 0.0–1.0 confidence score
    touches: int
    last_touch: str  # ISO timestamp


class SRLevelsResponse(BaseModel):
    """Complete S/R analysis for a symbol."""
    symbol: str
    current_price: float
    support_levels: List[SRLevel]
    resistance_levels: List[SRLevel]
    pivot_points: dict  # {"PP": float, "R1": float, "S1": float, ...}
    calculated_at: str  # ISO timestamp
    next_refresh: str   # ISO timestamp


class RefreshResponse(BaseModel):
    """Result of manual refresh operation."""
    refreshed: int
    symbols: List[str]
    timestamp: str


class ValidationResponse(BaseModel):
    """Result of level validation check."""
    is_at_level: bool
    level_type: Optional[str] = None  # "support" | "resistance"
    nearest_level: Optional[float] = None
    distance_pct: float
    strength: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/levels/{symbol}", response_model=SRLevelsResponse)
async def get_sr_levels(
    symbol: str,
    force_refresh: bool = Query(False, description="Force recalculation (ignore cache)"),
):
    """
    Get current support/resistance levels for a symbol.

    The service automatically refreshes levels daily at 9:00 AM IST.
    Use `force_refresh=true` to manually trigger recalculation.

    **Symbols:**
    - `NIFTY` — Nifty 50 index
    - `BANKNIFTY` — Bank Nifty index
    - Individual stocks: `RELIANCE`, `TCS`, etc.

    **Example:**
    ```
    GET /api/sr/levels/NIFTY?force_refresh=false
    ```

    **Response:**
    ```json
    {
      "symbol": "NIFTY",
      "current_price": 24500.0,
      "support_levels": [
        {"price": 24350.0, "strength": 0.85, "touches": 3, "last_touch": "2026-07-14T15:30:00+05:30"},
        {"price": 24200.0, "strength": 0.72, "touches": 2, "last_touch": "2026-07-13T14:15:00+05:30"}
      ],
      "resistance_levels": [
        {"price": 24650.0, "strength": 0.91, "touches": 4, "last_touch": "2026-07-15T11:00:00+05:30"},
        {"price": 24800.0, "strength": 0.68, "touches": 2, "last_touch": "2026-07-12T10:45:00+05:30"}
      ],
      "pivot_points": {
        "PP": 24500.0,
        "R1": 24610.0,
        "R2": 24720.0,
        "R3": 24830.0,
        "S1": 24390.0,
        "S2": 24280.0,
        "S3": 24170.0
      },
      "calculated_at": "2026-07-15T09:00:00+05:30",
      "next_refresh": "2026-07-16T09:00:00+05:30"
    }
    ```
    """
    try:
        sr_service = get_sr_service()
        result = await sr_service.get_levels(symbol.upper(), force_refresh=force_refresh)
        return result
    except Exception as exc:
        logger.error(f"[API/SR] get_levels failed for {symbol}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_levels(symbols: Optional[List[str]] = None):
    """
    Manually trigger S/R level refresh for specified symbols.

    Normally, levels auto-refresh daily at 9:00 AM IST. Use this endpoint
    to force immediate recalculation after significant market events.

    **Request Body:**
    ```json
    {
      "symbols": ["NIFTY", "BANKNIFTY", "RELIANCE"]
    }
    ```

    **Response:**
    ```json
    {
      "refreshed": 3,
      "symbols": ["NIFTY", "BANKNIFTY", "RELIANCE"],
      "timestamp": "2026-07-15T14:30:00+05:30"
    }
    ```
    """
    try:
        sr_service = get_sr_service()
        symbols_list = [s.upper() for s in symbols] if symbols else ["NIFTY"]
        result = await sr_service.refresh_daily(symbols_list)
        return result
    except Exception as exc:
        logger.error(f"[API/SR] refresh_levels failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/validate", response_model=ValidationResponse)
async def validate_level(
    symbol: str = Query(..., description="Symbol to check"),
    price: float = Query(..., description="Price to validate"),
    tolerance_pct: float = Query(0.5, description="% tolerance for 'at level' (default 0.5%)"),
):
    """
    Check if a price is near a known support/resistance level.

    Useful for:
    - Entry/exit validation: "Is current price at support? Should I buy?"
    - Alert triggering: "Price approaching resistance — notify me"
    - Risk management: "How far is my stop from the nearest support?"

    **Parameters:**
    - `symbol`: Stock/index symbol (e.g., `NIFTY`)
    - `price`: Price to validate (e.g., `24350.0`)
    - `tolerance_pct`: % distance to consider "at level" (default `0.5`)

    **Example:**
    ```
    GET /api/sr/validate?symbol=NIFTY&price=24350&tolerance_pct=0.5
    ```

    **Response:**
    ```json
    {
      "is_at_level": true,
      "level_type": "support",
      "nearest_level": 24350.0,
      "distance_pct": 0.0,
      "strength": 0.85
    }
    ```
    """
    try:
        sr_service = get_sr_service()
        result = sr_service.validate_level(symbol.upper(), price, tolerance_pct)
        return result
    except Exception as exc:
        logger.error(f"[API/SR] validate_level failed for {symbol}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health")
async def sr_health():
    """
    Health check for S/R service.

    Returns service status and cache info.
    """
    try:
        sr_service = get_sr_service()
        cache_size = len(sr_service._cache)
        last_refresh = sr_service._last_refresh.isoformat() if sr_service._last_refresh else None

        return {
            "status": "healthy",
            "service": "support_resistance",
            "cached_symbols": cache_size,
            "last_refresh": last_refresh,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as exc:
        logger.error(f"[API/SR] health check failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
