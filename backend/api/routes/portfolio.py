"""
Portfolio API routes.

GET  /api/portfolio/holdings         — return cached demat holdings (fast)
POST /api/portfolio/sync             — fresh sync from Angel One broker
GET  /api/portfolio/analysis/{sym}   — TA + FA + AI recommendation for one symbol
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _get_svc():
    from backend.services.portfolio_service import get_portfolio_service
    from backend.dependencies import get_angel_client
    return get_portfolio_service(get_angel_client())


@router.get("/holdings")
async def get_holdings():
    """Return last synced portfolio holdings (instant — no broker call)."""
    return _get_svc().get_cached()


@router.post("/sync")
async def sync_holdings():
    """Force a fresh sync from Angel One.  ~2–10 s depending on holding count."""
    try:
        return await _get_svc().sync()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Portfolio sync failed: {exc}")


@router.get("/analysis/{symbol}")
async def get_analysis(symbol: str):
    """TA + FA + AI recommendation for one symbol.  Results cached 1 hour."""
    svc      = _get_svc()
    cached   = svc.get_cached()
    holdings = cached.get("holdings", [])
    holding  = next((h for h in holdings if h["symbol"].upper() == symbol.upper()), {})
    try:
        from backend.services.portfolio_analysis_service import analyze_symbol
        return await analyze_symbol(symbol.upper(), holding)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")
