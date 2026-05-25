from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from typing import List
import time
import httpx

from backend.api.models.responses import SystemStatusResponse, LogEntry, ErrorResponse
from backend.api.models.requests import SystemModeRequest
from backend.dependencies import get_angel_client
from backend.config import DEMO_MODE

router = APIRouter(prefix="/api/system", tags=["system"])

# Store startup time
_startup_time = time.time()
_current_mode = "demo" if DEMO_MODE else "paper"


@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(angel_client=Depends(get_angel_client)):
    if DEMO_MODE:
        return SystemStatusResponse(
            status="healthy",
            broker_connected=False,
            websocket_connected=True,
            database_connected=True,
            uptime_seconds=int(time.time() - _startup_time),
            current_mode="demo"
        )
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


@router.get("/my-ip")
async def get_outbound_ip():
    """Return the server's outbound public IP — use this to whitelist in Angel One"""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get("https://api.ipify.org?format=json")
            ip = r.json().get("ip", "unknown")
        except Exception:
            try:
                r = await client.get("https://ifconfig.me/ip")
                ip = r.text.strip()
            except Exception as e:
                raise HTTPException(status_code=503, detail=f"Could not determine outbound IP: {e}")
    return {"outbound_ip": ip, "note": "Add this IP to Angel One SmartAPI whitelist"}
