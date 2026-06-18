"""
ETF Holdings API routes.

GET  /api/etf/holdings        — return cached holding list (fast)
POST /api/etf/sync            — force broker sync (hits Angel One / yfinance)
GET  /api/etf/config          — return current target gain %
POST /api/etf/config          — update target gain %
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from backend.config import DEMO_MODE

router = APIRouter(prefix="/api/etf", tags=["etf-holdings"])


class ETFConfigRequest(BaseModel):
    target_gain_pct: float = Field(..., gt=0, le=100, description="Auto-sell target gain % (e.g. 5.0)")


def _get_svc():
    from backend.services.etf_holdings_service import get_etf_holdings_service
    from backend.dependencies import get_angel_client
    return get_etf_holdings_service(get_angel_client())


@router.get("/holdings")
async def get_holdings():
    """Return last synced ETF holding list (instant — no broker call)."""
    svc = _get_svc()
    return {
        "holdings": svc.get_cached(),
        "last_sync": svc._last_sync.strftime("%d %b %Y %H:%M IST") if svc._last_sync else None,
    }


@router.post("/sync")
async def sync_holdings():
    """Force a fresh sync from Angel One + update P&L.  ~2–5s per holding."""
    svc = _get_svc()
    try:
        result = await svc.sync_and_check()
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Holdings sync failed: {exc}")


@router.get("/config")
async def get_etf_config():
    """Return current ETF auto-sell configuration."""
    from backend.services.etf_holdings_service import get_profit_target_pct
    return {"target_gain_pct": get_profit_target_pct()}


@router.post("/config")
async def update_etf_config(body: ETFConfigRequest):
    """Update ETF auto-sell target gain %.  Persists across restarts."""
    from backend.services.etf_holdings_service import set_profit_target_pct
    try:
        set_profit_target_pct(body.target_gain_pct)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"target_gain_pct": body.target_gain_pct, "updated": True}
