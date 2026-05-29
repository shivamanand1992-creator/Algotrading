"""
stocks.py — REST API routes for the Nifty50 swing trade screener.

Endpoints:
  GET  /api/stocks/scan                       — run screener (~15s)
  GET  /api/stocks/signals                    — cached last results
  GET  /api/stocks/watchlist                  — Nifty50 universe
  GET  /api/stocks/positions                  — open swing positions
  POST /api/stocks/signals/{symbol}/execute   — execute specific signal
  POST /api/stocks/auto-execute               — execute top N signals
"""

import sys
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from backend.api.models.responses import StockSignalResponse, SwingPositionResponse
from backend.config import config, DEMO_MODE
from backend.dependencies import get_angel_client
from backend.services.swing_trade_service import get_swing_service, SwingTradeService
from data.nifty50_universe import NIFTY50_UNIVERSE, NIFTY100_UNIVERSE

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

_DEMO_SIGNALS: List[dict] = [
    {
        "symbol": "RELIANCE", "name": "Reliance Industries", "sector": "Energy",
        "yf_ticker": "RELIANCE.NS", "action": "BUY",
        "close": 2980.55, "entry_price": 2980.55, "stop_loss": 2901.40,
        "target1": 3138.85, "target2": 3218.00, "sl_pct": 2.65,
        "risk_reward": 2.0, "confidence": 0.82, "regime": "uptrend",
        "reasons": ["Close > EMA21 > EMA50 (trend aligned)", "EMA9 > EMA21 (short-term bullish)",
                    "ADX=27.3 > 25 (strong trend)", "RSI=58.1 in 50–70 (momentum zone)",
                    "MACD histogram positive & rising"],
        "rsi": 58.1, "adx": 27.3, "atr": 52.8, "volume_ratio": 1.38,
        "macd_hist": 12.4, "ema9": 2965.0, "ema21": 2940.0, "ema50": 2880.0,
        "scan_time": "2024-05-27T16:05:00+05:30",
    },
    {
        "symbol": "TCS", "name": "Tata Consultancy Services", "sector": "IT",
        "yf_ticker": "TCS.NS", "action": "BUY",
        "close": 3850.20, "entry_price": 3850.20, "stop_loss": 3742.30,
        "target1": 4066.00, "target2": 4174.00, "sl_pct": 2.80,
        "risk_reward": 2.0, "confidence": 0.77, "regime": "uptrend",
        "reasons": ["Close > EMA21 > EMA50 (trend aligned)", "EMA9 > EMA21 (short-term bullish)",
                    "RSI=61.5 in 50–70 (momentum zone)", "MACD histogram positive & rising",
                    "Volume 1.6x avg (strong)"],
        "rsi": 61.5, "adx": 22.1, "atr": 71.9, "volume_ratio": 1.61,
        "macd_hist": 18.2, "ema9": 3835.0, "ema21": 3810.0, "ema50": 3740.0,
        "scan_time": "2024-05-27T16:05:00+05:30",
    },
    {
        "symbol": "HDFCBANK", "name": "HDFC Bank", "sector": "Banking",
        "yf_ticker": "HDFCBANK.NS", "action": "BUY",
        "close": 1742.80, "entry_price": 1742.80, "stop_loss": 1697.45,
        "target1": 1833.50, "target2": 1879.00, "sl_pct": 2.60,
        "risk_reward": 2.0, "confidence": 0.73, "regime": "uptrend",
        "reasons": ["Close > EMA21 > EMA50 (trend aligned)", "ADX=23.8 > 20 (moderate trend)",
                    "RSI=55.2 in 50–70 (momentum zone)", "MACD histogram positive & rising"],
        "rsi": 55.2, "adx": 23.8, "atr": 30.2, "volume_ratio": 1.24,
        "macd_hist": 5.6, "ema9": 1735.0, "ema21": 1720.0, "ema50": 1680.0,
        "scan_time": "2024-05-27T16:05:00+05:30",
    },
    {
        "symbol": "INFY", "name": "Infosys", "sector": "IT",
        "yf_ticker": "INFY.NS", "action": "BUY",
        "close": 1622.10, "entry_price": 1622.10, "stop_loss": 1574.30,
        "target1": 1717.70, "target2": 1765.50, "sl_pct": 2.95,
        "risk_reward": 2.0, "confidence": 0.68, "regime": "uptrend",
        "reasons": ["Close > EMA21 > EMA50 (trend aligned)", "RSI=52.8 in 50–70 (momentum zone)",
                    "MACD histogram positive & rising", "Candlestick: Bull Engulfing"],
        "rsi": 52.8, "adx": 18.4, "atr": 31.9, "volume_ratio": 1.43,
        "macd_hist": 4.1, "ema9": 1615.0, "ema21": 1598.0, "ema50": 1555.0,
        "scan_time": "2024-05-27T16:05:00+05:30",
    },
    {
        "symbol": "SUNPHARMA", "name": "Sun Pharmaceutical", "sector": "Pharma",
        "yf_ticker": "SUNPHARMA.NS", "action": "BUY",
        "close": 1485.60, "entry_price": 1485.60, "stop_loss": 1444.85,
        "target1": 1566.10, "target2": 1606.40, "sl_pct": 2.74,
        "risk_reward": 2.0, "confidence": 0.63, "regime": "uptrend",
        "reasons": ["Close > EMA21 > EMA50 (trend aligned)", "ADX=21.2 > 20 (moderate trend)",
                    "RSI=56.9 in 50–70 (momentum zone)"],
        "rsi": 56.9, "adx": 21.2, "atr": 27.2, "volume_ratio": 1.08,
        "macd_hist": 2.9, "ema9": 1478.0, "ema21": 1462.0, "ema50": 1420.0,
        "scan_time": "2024-05-27T16:05:00+05:30",
    },
]

_DEMO_POSITIONS: List[dict] = []  # no demo positions open by default


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

def _get_svc() -> SwingTradeService:
    angel = get_angel_client()
    return get_swing_service(config.trading_config, angel)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    mode: str = "paper"   # "paper" | "live"
    capital: Optional[float] = None


class AutoExecuteRequest(BaseModel):
    mode: str = "paper"
    max_signals: int = 3
    capital: Optional[float] = None


class AutopilotConfig(BaseModel):
    enabled: bool
    mode: str = "paper"
    capital_per_trade: float = 1000.0
    max_trades: int = 3


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/watchlist")
async def get_watchlist(universe: str = Query("nifty50", enum=["nifty50", "nifty100"])):
    """Return the stock universe list."""
    src = NIFTY100_UNIVERSE if universe == "nifty100" else NIFTY50_UNIVERSE
    return [{"symbol": s["symbol"], "name": s["name"], "sector": s["sector"]} for s in src]


@router.get("/signals", response_model=List[StockSignalResponse])
async def get_signals(svc: SwingTradeService = Depends(_get_svc)):
    """Return cached last-scan results (instant)."""
    if DEMO_MODE:
        return [StockSignalResponse(**d) for d in _DEMO_SIGNALS]
    return [StockSignalResponse(**s.to_dict()) for s in svc.get_last_signals()]


@router.get("/scan")
async def run_scan(
    universe:      str  = Query("nifty50", enum=["nifty50", "nifty100"]),
    regime_filter: bool = Query(True),
    rs_filter:     bool = Query(True),
    svc: SwingTradeService = Depends(_get_svc),
):
    """
    Run a fresh swing scan.
    universe=nifty50|nifty100 · regime_filter=true|false · rs_filter=true|false
    Returns {signals, regime_warning, nifty_bullish, nifty_20d_return, universe_size}
    """
    if DEMO_MODE:
        return {
            "signals": [StockSignalResponse(**d).model_dump() for d in _DEMO_SIGNALS],
            "regime_warning": "",
            "nifty_bullish": True,
            "nifty_20d_return": 1.2,
            "universe_size": len(_DEMO_SIGNALS),
        }

    filters = {"regime_filter": regime_filter, "rs_filter": rs_filter}
    signals, regime_info = await svc.run_scan(universe=universe, filters=filters)
    return {
        "signals":        [StockSignalResponse(**s.to_dict()).model_dump() for s in signals],
        "regime_warning": regime_info.get("warning", ""),
        "nifty_bullish":  regime_info.get("bullish", True),
        "nifty_20d_return": regime_info.get("nifty_20d_ret", 0.0),
        "universe_size":  len(signals),
    }


@router.get("/positions", response_model=List[SwingPositionResponse])
async def get_positions(svc: SwingTradeService = Depends(_get_svc)):
    """Return currently open swing positions with live P&L."""
    if DEMO_MODE:
        return []
    await svc.refresh_position_prices()   # live LTP update (throttled to 30s)
    return [SwingPositionResponse(**p) for p in svc.get_positions()]


@router.post("/signals/{symbol}/execute")
async def execute_signal(
    symbol: str,
    req: ExecuteRequest,
    svc: SwingTradeService = Depends(_get_svc),
):
    """Execute a swing trade for *symbol* from the last scan."""
    if DEMO_MODE:
        return {"success": True, "order_id": f"DEMO-SWING-{symbol}", "message": f"Demo: {symbol} paper order simulated"}

    if req.mode == "live" and get_angel_client() is None:
        raise HTTPException(status_code=503, detail="Broker not connected — cannot place live order")

    order_id = await svc.execute_signal(symbol, req.mode, position_value=req.capital)
    if order_id is None:
        raise HTTPException(status_code=400, detail=f"Could not execute {symbol} — check logs for reason")

    return {"success": True, "order_id": order_id, "message": f"{req.mode.capitalize()} order placed for {symbol}"}


@router.post("/auto-execute")
async def auto_execute(
    req: AutoExecuteRequest,
    svc: SwingTradeService = Depends(_get_svc),
):
    """Auto-execute top N high-confidence signals."""
    if DEMO_MODE:
        return {"success": True, "executed": [], "message": "Demo mode — no orders placed"}

    if req.mode == "live" and get_angel_client() is None:
        raise HTTPException(status_code=503, detail="Broker not connected — cannot place live orders")

    order_ids = await svc.auto_execute_top_signals(req.mode, req.max_signals, position_value=req.capital)
    return {
        "success": True,
        "executed": order_ids,
        "count":   len(order_ids),
        "message": f"{len(order_ids)} {req.mode} orders placed",
    }


@router.post("/sync-from-broker")
async def sync_from_broker(svc: SwingTradeService = Depends(_get_svc)):
    """
    Fetch actual CNC holdings from Angel One and reconcile with local swing position state.
    Use after a server restart that lost in-memory positions, or to detect external sells.
    """
    if DEMO_MODE:
        return {"imported": [], "updated": [], "orphaned": [], "total_broker_holdings": 0,
                "message": "Demo mode — no broker to sync from"}
    result = await svc.sync_from_broker()
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    msg_parts = []
    if result["imported"]:
        msg_parts.append(f"Imported: {', '.join(result['imported'])}")
    if result["updated"]:
        msg_parts.append(f"Updated qty: {', '.join(result['updated'])}")
    if result["orphaned"]:
        msg_parts.append(f"Orphaned (not on broker): {', '.join(result['orphaned'])}")
    if not msg_parts:
        msg_parts.append("Already in sync — no changes needed")
    return {**result, "message": " | ".join(msg_parts)}


@router.delete("/positions/{symbol}")
async def close_position(symbol: str, svc: SwingTradeService = Depends(_get_svc)):
    """Manually close an open swing position."""
    if DEMO_MODE:
        return {"success": True, "message": f"Demo: {symbol} position closed"}

    closed = svc.close_position(symbol, reason="manual_close")
    if not closed:
        raise HTTPException(status_code=404, detail=f"No open position found for {symbol}")
    return {"success": True, "message": f"{symbol} position closed"}


@router.get("/autopilot")
async def get_autopilot(svc: SwingTradeService = Depends(_get_svc)):
    """Return current autopilot configuration and last run result."""
    if DEMO_MODE:
        return {
            "enabled": False, "mode": "paper",
            "capital_per_trade": 1000.0, "max_trades": 3,
            "last_run": None, "last_result": {},
        }
    return svc.get_autopilot_config()


@router.post("/autopilot")
async def set_autopilot(cfg: AutopilotConfig, svc: SwingTradeService = Depends(_get_svc)):
    """Enable / disable autopilot and update its configuration."""
    if DEMO_MODE:
        return {"success": True, "config": cfg.model_dump()}
    svc.set_autopilot(cfg.enabled, cfg.mode, cfg.capital_per_trade, cfg.max_trades)
    return {"success": True, "config": svc.get_autopilot_config()}


@router.post("/autopilot/run-now")
async def run_autopilot_now(svc: SwingTradeService = Depends(_get_svc)):
    """Manually trigger an autopilot scan + execute cycle immediately."""
    if DEMO_MODE:
        return {
            "skipped": False, "signals_found": 5, "executed_count": 3,
            "executed": [
                {"symbol": "RELIANCE", "qty": 1, "entry": 2980.55, "invested": 2980.55, "confidence": 0.82},
                {"symbol": "TCS",      "qty": 1, "entry": 3850.20, "invested": 3850.20, "confidence": 0.77},
                {"symbol": "HDFCBANK", "qty": 1, "entry": 1742.80, "invested": 1742.80, "confidence": 0.73},
            ],
            "regime_warning": "", "nifty_bullish": True,
        }
    if not svc._autopilot_enabled:
        raise HTTPException(status_code=400, detail="Autopilot is disabled — enable it first")
    result = await svc.run_autopilot()
    return result
