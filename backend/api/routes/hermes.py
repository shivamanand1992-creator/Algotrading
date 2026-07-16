"""
Hermes AI Agent - API Routes
Control and monitor the Hermes intraday trading agent
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from loguru import logger

from backend.config import config, DEMO_MODE
from backend.dependencies import get_angel_client


router = APIRouter(prefix="/api/hermes", tags=["Hermes Agent"])


# Global Hermes service instance (initialized on startup)
_hermes_service: Optional[object] = None


def _get_hermes():
    """Dependency: get Hermes service instance"""
    global _hermes_service
    if _hermes_service is None:
        from backend.services.hermes_intraday_service import HermesIntradayService
        angel = get_angel_client()
        _hermes_service = HermesIntradayService(config.trading_config, angel)
    return _hermes_service


class HermesConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    instrument: Optional[str] = None
    capital_per_trade: Optional[float] = None
    max_trades_per_day: Optional[int] = None
    min_confidence: Optional[float] = None


@router.get("/status")
async def get_hermes_status(svc = Depends(_get_hermes)):
    """Get current Hermes agent status"""
    if DEMO_MODE:
        return {"demo": True, "enabled": False, "message": "Hermes not available in demo mode"}

    return svc.get_status()


@router.post("/config")
async def update_hermes_config(update: HermesConfigUpdate, svc = Depends(_get_hermes)):
    """Update Hermes configuration"""
    if DEMO_MODE:
        return {"demo": True, "message": "Hermes not available in demo mode"}

    if update.enabled is not None:
        svc.enabled = update.enabled
        logger.info(f"[Hermes API] Enabled={update.enabled}")

    if update.instrument:
        svc.instrument = update.instrument
        logger.info(f"[Hermes API] Instrument={update.instrument}")

    if update.capital_per_trade:
        svc.capital_per_trade = update.capital_per_trade
        logger.info(f"[Hermes API] Capital per trade=₹{update.capital_per_trade}")

    if update.max_trades_per_day:
        svc.max_trades_per_day = update.max_trades_per_day
        logger.info(f"[Hermes API] Max trades={update.max_trades_per_day}")

    if update.min_confidence:
        svc.min_confidence = update.min_confidence
        logger.info(f"[Hermes API] Min confidence={update.min_confidence}")

    svc._save_state()

    return {
        "success": True,
        "config": {
            "enabled": svc.enabled,
            "instrument": svc.instrument,
            "capital_per_trade": svc.capital_per_trade,
            "max_trades_per_day": svc.max_trades_per_day,
            "min_confidence": svc.min_confidence,
        }
    }


@router.post("/force-exit")
async def force_exit_position(svc = Depends(_get_hermes)):
    """Manually exit current Hermes position"""
    if DEMO_MODE:
        return {"demo": True, "message": "Hermes not available in demo mode"}

    if not svc.position:
        raise HTTPException(status_code=400, detail="No open position to exit")

    market_data = await svc._fetch_market_data()
    result = await svc._exit_position(market_data, reason="manual")

    return {"success": True, "result": result}


@router.get("/trades/today")
async def get_today_trades(svc = Depends(_get_hermes)):
    """Get all Hermes trades executed today"""
    if DEMO_MODE:
        return {"demo": True, "trades": []}

    return {
        "trades": svc.trades_today,
        "count": len(svc.trades_today),
        "daily_pnl": svc.daily_pnl,
    }


@router.post("/run-analysis")
async def run_single_analysis(svc = Depends(_get_hermes)):
    """Manually trigger a single Hermes analysis cycle"""
    if DEMO_MODE:
        return {"demo": True, "message": "Hermes not available in demo mode"}

    if not svc.enabled:
        raise HTTPException(status_code=400, detail="Hermes is disabled")

    result = await svc.run_analysis_cycle()
    return result
