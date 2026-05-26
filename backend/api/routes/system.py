from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from typing import List
import asyncio
import time
import httpx

from backend.api.models.responses import SystemStatusResponse, LogEntry, ErrorResponse
from backend.api.models.requests import SystemModeRequest
from backend.dependencies import get_angel_client, reset_angel_client, reload_ml_models
from backend.config import config, DEMO_MODE

router = APIRouter(prefix="/api/system", tags=["system"])

# Store startup time
_startup_time = time.time()
_current_mode = "demo" if DEMO_MODE else "paper"

# Training state
_train_status = "idle"   # idle | running | complete | failed
_train_progress = ""
_train_error = ""


def _update_progress(msg: str) -> None:
    global _train_progress
    _train_progress = msg


def _do_train(angel_client, days: int) -> None:
    """Synchronous training — runs in a thread executor."""
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent.parent.parent))
    from models.model_trainer import ModelTrainer
    trainer = ModelTrainer(angel_client, config.trading_config)
    trainer.train_days = days  # override config default with user-supplied value
    trainer.train_all_models(on_step=_update_progress)


async def _run_training(angel_client, days: int) -> None:
    global _train_status, _train_progress, _train_error
    _train_status = "running"
    _train_progress = f"Fetching {days} days of historical data and training models..."
    _train_error = ""
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_train, angel_client, days)
        reload_ml_models()
        _train_status = "complete"
        _train_progress = "Models trained successfully and loaded into memory."
    except Exception as e:
        _train_status = "failed"
        _train_error = str(e)
        _train_progress = ""


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
        broker_connected = angel_client is not None

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


@router.post("/reconnect")
async def reconnect_broker():
    """Force a fresh Angel One connection attempt (after whitelisting IP or fixing credentials)."""
    reset_angel_client()
    client = get_angel_client()
    if client is not None:
        return {"success": True, "message": "Angel One reconnected successfully"}
    return {"success": False, "message": "Reconnect failed — check credentials and IP whitelist"}


@router.post("/train")
async def start_training(days: int = 252, force: bool = False, angel_client=Depends(get_angel_client)):
    """Train ML models using Angel One historical data. Runs as a background task."""
    global _train_status
    if DEMO_MODE:
        raise HTTPException(status_code=400, detail="Training not available in demo mode")
    if _train_status == "running":
        raise HTTPException(status_code=409, detail="Training already in progress")
    if angel_client is None:
        raise HTTPException(status_code=503, detail="Broker not connected — cannot fetch training data")
    # Set status synchronously before spawning so rapid duplicate clicks get a 409
    _train_status = "running"
    _train_progress = f"Starting — will fetch {days} days of Nifty50 data…"
    _train_error = ""
    asyncio.create_task(_run_training(angel_client, days))
    return {
        "started": True,
        "message": f"Training started in background ({days} days of data). ETA ~10-15 min. Poll /api/system/train/status."
    }


@router.get("/train/status")
async def get_training_status():
    """Poll the current ML model training status."""
    return {
        "status": _train_status,
        "progress": _train_progress,
        "error": _train_error,
    }


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
