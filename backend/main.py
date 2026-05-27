import sys
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta, date as _date

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.requests import Request
from contextlib import asynccontextmanager
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

from backend.config import config
from backend.api.routes import (
    system,
    strategies,
    positions,
    trades,
    market_data,
    risk,
    stocks,
)
from backend.api.routes import auth as auth_routes
from backend.auth import verify_token
from backend.dependencies import cleanup_dependencies
from backend.websocket_manager import ws_manager

_IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# EOD auto square-off — runs at 15:15 IST every weekday
# ---------------------------------------------------------------------------

async def _eod_squareoff_loop() -> None:
    """Background task: square off all positions at 15:15 IST on trading days."""
    last_squareoff_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday         = today.weekday() < 5          # Mon–Fri
            past_cutoff        = (now_ist.hour, now_ist.minute) >= (15, 15)
            not_done_today     = last_squareoff_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_squareoff_date = today
                logger.warning("EOD 15:15 — auto square-off triggered.")

                # Stop all running strategies first
                try:
                    from backend.api.routes.strategies import get_strategy_service
                    svc = get_strategy_service()
                    for name in list(svc.running_strategies.keys()):
                        await svc.stop_strategy(name)
                        logger.info(f"EOD: strategy '{name}' stopped.")
                except Exception as exc:
                    logger.error(f"EOD strategy stop error: {exc}")

                # Square off all open positions
                try:
                    from backend.dependencies import get_order_manager
                    loop = asyncio.get_event_loop()
                    om = get_order_manager()
                    await loop.run_in_executor(
                        None, om.exit_all_positions, "EOD auto square-off 15:15"
                    )
                    logger.info("EOD: all positions squared off.")
                except Exception as exc:
                    logger.error(f"EOD square-off error: {exc}")

        except Exception as exc:
            logger.error(f"_eod_squareoff_loop unexpected error: {exc}")

        await asyncio.sleep(60)  # check every minute


# ---------------------------------------------------------------------------
# Swing autopilot — scan + auto-execute top 3 at 15:35 IST every weekday
# ---------------------------------------------------------------------------

async def _swing_autopilot_loop() -> None:
    """Daily 15:35 IST: run scan and auto-execute top N signals if autopilot is enabled."""
    last_autopilot_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday     = today.weekday() < 5
            past_cutoff    = (now_ist.hour, now_ist.minute) >= (15, 35)
            not_done_today = last_autopilot_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_autopilot_date = today
                try:
                    from backend.api.routes.stocks import _get_svc
                    svc = _get_svc()
                    if svc._autopilot_enabled:
                        logger.info("15:35 IST — Swing autopilot triggered.")
                        result = await svc.run_autopilot()
                        logger.info(
                            f"[SwingAutopilot] {result.get('executed_count', 0)} trades executed "
                            f"from {result.get('signals_found', 0)} signals."
                        )
                    else:
                        logger.debug("15:35 IST — Swing autopilot disabled, skipping.")
                except Exception as exc:
                    logger.error(f"Swing autopilot error: {exc}")

        except Exception as exc:
            logger.error(f"_swing_autopilot_loop unexpected error: {exc}")

        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Swing position monitor — runs at 16:00 IST every weekday after market close
# ---------------------------------------------------------------------------

async def _swing_monitor_loop() -> None:
    """Update MTM prices and check SL/target for open swing positions daily."""
    last_monitor_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday     = today.weekday() < 5
            past_cutoff    = (now_ist.hour, now_ist.minute) >= (16, 0)
            not_done_today = last_monitor_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_monitor_date = today
                logger.info("16:00 IST — swing position monitor triggered.")
                try:
                    from backend.api.routes.stocks import _get_svc
                    svc = _get_svc()
                    await svc.monitor_positions()
                except Exception as exc:
                    logger.error(f"Swing monitor error: {exc}")

        except Exception as exc:
            logger.error(f"_swing_monitor_loop unexpected error: {exc}")

        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Morning auto-retrain — runs at 08:30 IST every weekday
# ---------------------------------------------------------------------------

async def _morning_retrain_loop() -> None:
    """Background task: retrain ML models at 08:30 IST on trading days."""
    last_retrain_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday     = today.weekday() < 5
            past_cutoff    = (now_ist.hour, now_ist.minute) >= (8, 30)
            not_done_today = last_retrain_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_retrain_date = today
                logger.info("Morning 08:30 — scheduled model retrain starting.")

                try:
                    from backend.api.routes.system import _run_training
                    from backend.dependencies import get_angel_client
                    angel_client = get_angel_client()
                    if angel_client is None:
                        logger.warning("Morning retrain skipped — broker not connected.")
                    else:
                        asyncio.create_task(_run_training(angel_client, days=60))
                        logger.info("Morning retrain task launched (60 days, ~10–15 min).")
                except Exception as exc:
                    logger.error(f"Morning retrain error: {exc}")

        except Exception as exc:
            logger.error(f"_morning_retrain_loop unexpected error: {exc}")

        await asyncio.sleep(60)  # check every minute


# ---------------------------------------------------------------------------
# Auth middleware — protects all /api/* paths except public endpoints
# ---------------------------------------------------------------------------
_PUBLIC_API_PATHS = {
    "/api/auth/login",
    "/api/system/status",  # Railway health check
    "/health",
}

class _AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Pass through: static files, frontend routes, public API paths, WS
        if (
            not path.startswith("/api")
            or path in _PUBLIC_API_PATHS
            or path.startswith("/ws/")
        ):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        token = auth_header.split(" ", 1)[1]
        try:
            verify_token(token)
        except Exception:
            return JSONResponse({"detail": "Token invalid or expired"}, status_code=401)

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting FastAPI backend...")
    from backend.api.routes.positions import get_position_service
    from backend.api.routes.market_data import get_market_service
    asyncio.create_task(
        ws_manager.start_periodic_updates(get_position_service(), get_market_service())
    )
    asyncio.create_task(_eod_squareoff_loop())
    asyncio.create_task(_morning_retrain_loop())
    asyncio.create_task(_swing_autopilot_loop())
    asyncio.create_task(_swing_monitor_loop())
    yield
    print("Shutting down FastAPI backend...")
    cleanup_dependencies()


app = FastAPI(
    title="Algotrading API",
    description="JARVIS-style algorithmic trading platform API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,   # disable /docs in production
    redoc_url=None,
)

# CORS must be added before AuthMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(_AuthMiddleware)

# Include API routers
app.include_router(auth_routes.router)   # /api/auth/* — public login endpoint
app.include_router(system.router)
app.include_router(strategies.router)
app.include_router(positions.router)
app.include_router(trades.router)
app.include_router(market_data.router)
app.include_router(risk.router)
app.include_router(stocks.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket, token: str = ""):
    # Validate token passed as query param: /ws/live?token=<jwt>
    try:
        verify_token(token)
    except Exception:
        await websocket.accept()
        await websocket.close(code=4001)  # 4001 = unauthorised
        return
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({"type": "ack", "data": data})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# Serve React frontend — mount AFTER all API routes
_frontend_build = Path(__file__).parent.parent / "frontend" / "build"
if _frontend_build.exists():
    app.mount("/static", StaticFiles(directory=str(_frontend_build / "static")), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        return FileResponse(str(_frontend_build / "index.html"))
else:
    @app.get("/")
    async def root():
        return {"message": "Algotrading API v1.0.0 — frontend not built yet"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=int(__import__("os").getenv("PORT", 8000)), log_level="info")
