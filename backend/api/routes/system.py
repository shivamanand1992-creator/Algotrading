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
    import os
    from pathlib import Path as _Path

    status = _train_status
    progress = _train_progress
    error = _train_error

    # After a restart, _train_status resets to "idle" even if model files exist
    # on the Volume. Check the files so the dashboard shows Ready correctly.
    if status == "idle":
        _default = str(_Path(__file__).parent.parent.parent.parent / "trained_models")
        model_dir = _Path(os.getenv("MODEL_SAVE_PATH", _default))
        if (model_dir / "regime_classifier_meta.pkl").exists():
            status = "complete"
            progress = "Models loaded from disk (previous training session)."

    return {"status": status, "progress": progress, "error": error}


@router.post("/squareoff")
async def manual_squareoff():
    """Immediately square off all open positions and stop all running strategies."""
    results = {"strategies_stopped": [], "positions_closed": [], "errors": []}

    # Stop all running strategies
    try:
        from backend.api.routes.strategies import get_strategy_service
        svc = get_strategy_service()
        for name in list(svc.running_strategies.keys()):
            await svc.stop_strategy(name)
            results["strategies_stopped"].append(name)
    except Exception as exc:
        results["errors"].append(f"Strategy stop: {exc}")

    # Square off all positions
    try:
        from backend.dependencies import get_order_manager
        loop = asyncio.get_event_loop()
        om = get_order_manager()
        exit_ids = await loop.run_in_executor(
            None, om.exit_all_positions, "Manual square-off"
        )
        results["positions_closed"] = exit_ids
    except Exception as exc:
        results["errors"].append(f"Square-off: {exc}")

    return {
        "success": len(results["errors"]) == 0,
        "message": (
            f"Squared off {len(results['positions_closed'])} position(s), "
            f"stopped {len(results['strategies_stopped'])} strategy(s)."
        ),
        **results,
    }


@router.get("/balance")
async def get_account_balance(angel_client=Depends(get_angel_client)):
    """Fetch live Angel One account balance (available cash, net value, used margin)."""
    if DEMO_MODE:
        return {"available_cash": 85000.0, "net": 125000.0, "used_margin": 40000.0, "collateral": 0.0, "source": "demo"}
    if angel_client is None:
        return {"available_cash": 0.0, "net": 0.0, "used_margin": 0.0, "error": "broker_not_connected"}
    try:
        loop = asyncio.get_event_loop()
        raw  = await loop.run_in_executor(None, angel_client.get_funds)
        # rmsLimit keys: net, availablecash, utiliseddebits, collateral
        avail  = float(raw.get("availablecash",  raw.get("available_cash",  0)) or 0)
        net    = float(raw.get("net",            0) or 0)
        used   = float(raw.get("utiliseddebits", raw.get("used_margin", 0)) or 0)
        collat = float(raw.get("collateral",     0) or 0)
        return {"available_cash": avail, "net": net, "used_margin": used, "collateral": collat, "source": "live"}
    except Exception as exc:
        return {"available_cash": 0.0, "net": 0.0, "used_margin": 0.0, "error": str(exc)}


@router.post("/sync")
async def sync_all_from_broker(angel_client=Depends(get_angel_client)):
    """Sync all positions from Angel One — swing holdings + NiftyBees holdings."""
    if DEMO_MODE:
        return {"success": True, "message": "Demo mode — no sync needed", "imported": [], "niftybees_synced": False}

    results = {"swing": {}, "niftybees": {}, "errors": []}

    # Swing sync
    try:
        from backend.api.routes.stocks import _get_svc
        svc = _get_svc()
        r   = await svc.sync_from_broker()
        results["swing"] = r
    except Exception as exc:
        results["errors"].append(f"Swing sync: {exc}")

    # NiftyBees sync — check Angel One holdings for NIFTYBEES
    try:
        from backend.services.niftybees_service import get_niftybees_service
        nb = get_niftybees_service(angel_client)
        if angel_client:
            loop = asyncio.get_event_loop()
            holdings = await loop.run_in_executor(None, angel_client.get_holdings)
            nb_holding = next(
                (h for h in holdings
                 if h.get("tradingsymbol", "").upper() in ("NIFTYBEES", "NIFTY BEES")),
                None
            )
            if nb_holding:
                qty = int(nb_holding.get("quantity", 0))
                avg = float(nb_holding.get("averageprice", 0))
                cur = float(nb_holding.get("ltp", avg))
                if qty > 0 and (nb._position is None or not nb._position.get("active")):
                    # Restore position from broker
                    import json as _json
                    from datetime import date
                    nb._position = {
                        "active": True,
                        "buys": [{"date": str(date.today()), "qty": qty, "price": avg,
                                  "nifty_at_buy": 0, "nifty_dip_pct": 0,
                                  "order_id": "broker_sync", "invested": round(qty * avg, 2)}],
                        "total_qty": qty,
                        "total_invested": round(qty * avg, 2),
                        "avg_entry_price": avg,
                        "mode": nb._config.get("mode", "live"),
                        "last_buy_date": str(date.today()),
                        "current_price": cur,
                        "unrealized_pnl": round((cur - avg) * qty, 2),
                        "pnl_pct": round((cur - avg) / avg * 100, 2) if avg > 0 else 0.0,
                        "last_checked": str(date.today()),
                    }
                    await loop.run_in_executor(None, nb._save_state)
                    results["niftybees"] = {"synced": True, "qty": qty, "avg": avg}
                elif qty > 0:
                    results["niftybees"] = {"synced": False, "message": "Position already tracked", "qty": qty}
                else:
                    results["niftybees"] = {"synced": False, "message": "No NIFTYBEES holding in Angel One"}
            else:
                results["niftybees"] = {"synced": False, "message": "NIFTYBEES not found in holdings"}
    except Exception as exc:
        results["errors"].append(f"NiftyBees sync: {exc}")

    return {
        "success": len(results["errors"]) == 0,
        "message": f"Sync complete. Swing: {results['swing'].get('message', 'done')}",
        **results,
    }


@router.post("/telegram/test")
async def test_telegram():
    """Send a test Telegram message to verify bot configuration."""
    from backend.services.telegram_service import send, is_configured
    if not is_configured():
        return {"sent": False, "error": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in env vars"}
    ok = send("✅ *JARVIS connected!* Your Telegram notifications are working.")
    return {"sent": ok, "error": None if ok else "Send failed — check bot token and chat ID"}


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
