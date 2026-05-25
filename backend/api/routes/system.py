from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from typing import List
import time

from backend.api.models.responses import SystemStatusResponse, LogEntry, ErrorResponse
from backend.api.models.requests import SystemModeRequest
from backend.dependencies import get_angel_client

router = APIRouter(prefix="/api/system", tags=["system"])

# Store startup time
_startup_time = time.time()
_current_mode = "paper"


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(angel_client=Depends(get_angel_client)):
    """Get system health status"""
    try:
        # Check broker connection
        broker_connected = True  # TODO: Implement actual check

        uptime = int(time.time() - _startup_time)

        return SystemStatusResponse(
            status="healthy",
            broker_connected=broker_connected,
            websocket_connected=True,
            database_connected=True,
            uptime_seconds=uptime,
            current_mode=_current_mode
        )
    except Exception as e:
        return SystemStatusResponse(
            status="degraded",
            broker_connected=False,
            websocket_connected=False,
            database_connected=False,
            uptime_seconds=0,
            current_mode=_current_mode
        )


@router.get("/logs", response_model=List[LogEntry])
async def get_recent_logs(limit: int = 50):
    """Get recent log entries"""
    # TODO: Read from log files
    return []


@router.post("/mode")
async def set_system_mode(request: SystemModeRequest):
    """Switch system mode (paper/live/backtest)"""
    global _current_mode
    _current_mode = request.mode
    return {"message": f"Mode switched to {request.mode}"}
