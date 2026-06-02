"""
niftybees.py — REST API routes for the NiftyBees ETF autopilot.

Endpoints:
  GET  /api/niftybees/status     — config + position + recent history
  POST /api/niftybees/config     — update autopilot config
  POST /api/niftybees/check      — manually trigger monitor cycle
  DELETE /api/niftybees/position — manually close / reset tracked position
"""

import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from backend.config import DEMO_MODE
from backend.dependencies import get_angel_client
from backend.services.niftybees_service import get_niftybees_service, NiftyBeesService

router = APIRouter(prefix="/api/niftybees", tags=["niftybees"])


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

def _get_svc() -> NiftyBeesService:
    return get_niftybees_service(get_angel_client())


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

_DEMO_STATUS = {
    "config": {
        "enabled":           False,
        "mode":              "paper",
        "capital_amount":    10000.0,
        "dip_threshold_pct": 1.0,
        "target_gain_pct":   5.0,
    },
    "position": None,
    "history":  [],
}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class NiftyBeesConfigRequest(BaseModel):
    enabled:            Optional[bool]  = None
    mode:               Optional[str]   = None   # "paper" | "live"
    capital_amount:     Optional[float] = None
    dip_threshold_pct:  Optional[float] = None
    target_gain_pct:    Optional[float] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_status():
    """Return current config, open position, and last 20 closed trades."""
    if DEMO_MODE:
        return _DEMO_STATUS
    svc = _get_svc()
    return svc.get_status()


@router.post("/config")
async def update_config(req: NiftyBeesConfigRequest):
    """Update autopilot config (partial update — send only fields to change)."""
    if DEMO_MODE:
        return {"success": True, "config": _DEMO_STATUS["config"]}

    if req.mode is not None and req.mode not in ("paper", "live"):
        raise HTTPException(status_code=400, detail="mode must be 'paper' or 'live'")
    if req.mode == "live" and get_angel_client() is None:
        raise HTTPException(status_code=503, detail="Broker not connected — cannot enable live mode")

    svc    = _get_svc()
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    svc.set_config(**kwargs)
    return {"success": True, "config": svc.get_status()["config"]}


@router.post("/check")
async def trigger_check():
    """Manually run one monitor cycle — useful for testing or forcing a check."""
    if DEMO_MODE:
        return {"action": "demo", "details": "Demo mode — no real check performed"}
    svc    = _get_svc()
    result = await svc.run_monitor()
    return result


@router.delete("/position")
async def close_position():
    """
    Mark the tracked NiftyBees position as manually closed.
    Use this when you've sold the ETF in Angel One outside the system,
    or want to reset the tracker.
    """
    if DEMO_MODE:
        return {"success": True, "message": "Demo mode"}
    svc    = _get_svc()
    closed = svc.close_position_manual(reason="manual_close")
    if not closed:
        raise HTTPException(status_code=404, detail="No active NiftyBees position to close")
    return {"success": True, "message": "NiftyBees position closed and recorded in history"}
