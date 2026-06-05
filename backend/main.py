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
    niftybees,
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
    """
    Daily 09:20 IST: scan Nifty50 (using prev-day EOD data) then immediately
    place buy orders — market has been open for 5 minutes so orders execute.
    """
    last_autopilot_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday     = today.weekday() < 5
            past_cutoff    = (now_ist.hour, now_ist.minute) >= (9, 20)
            not_done_today = last_autopilot_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_autopilot_date = today
                try:
                    from backend.api.routes.stocks import _get_svc
                    svc = _get_svc()
                    logger.info(
                        f"[SwingAutopilot] 09:20 IST check — "
                        f"autopilot={'ON' if svc._autopilot_enabled else 'OFF'}, "
                        f"open_positions={len(svc._swing_positions)}, "
                        f"mode={svc._autopilot_mode}"
                    )
                    if svc._autopilot_enabled:
                        result = await svc.run_autopilot()
                        logger.info(
                            f"[SwingAutopilot] Complete: {result.get('executed_count', 0)} trades from "
                            f"{result.get('signals_found', 0)} signals. "
                            f"regime_warning={result.get('regime_warning', '')}"
                        )
                    else:
                        logger.info("[SwingAutopilot] Disabled — set enabled=True via /api/stocks/autopilot to activate.")
                except Exception as exc:
                    logger.error(f"Swing autopilot error: {exc}")

        except Exception as exc:
            logger.error(f"_swing_autopilot_loop unexpected error: {exc}")

        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Swing position monitor — runs at 15:20 IST (market still open — can exit)
# ---------------------------------------------------------------------------

async def _swing_monitor_loop() -> None:
    """Check intraday SL/target for open swing positions and exit before close."""
    last_monitor_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()

            is_weekday     = today.weekday() < 5
            past_cutoff    = (now_ist.hour, now_ist.minute) >= (15, 20)
            not_done_today = last_monitor_date != today

            if is_weekday and past_cutoff and not_done_today:
                last_monitor_date = today
                logger.info("15:20 IST — swing position monitor triggered (market still open).")
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
# Real-time intraday SL / target monitor — checks every 10s, 09:15–15:30 IST
# ---------------------------------------------------------------------------

async def _swing_intraday_sl_loop() -> None:
    """
    Every 10 seconds during market hours, check open swing positions against
    their stop-loss and targets using live WebSocket ticks (with REST fallback).
    Creates one LiveFeed per trading day; tears it down after market close.
    """
    _live_feed = None
    _feed_attached = False
    last_reset_date = None

    while True:
        try:
            now_ist    = datetime.now(_IST)
            is_weekday = now_ist.weekday() < 5
            hm         = (now_ist.hour, now_ist.minute)
            in_hours   = (9, 15) <= hm <= (15, 30)

            if is_weekday and in_hours:
                from backend.api.routes.stocks import _get_svc
                from backend.dependencies import get_angel_client
                svc = _get_svc()

                # Reset daily "already triggered" guard at market open
                today = now_ist.date()
                if last_reset_date != today:
                    svc._sl_triggered.clear()
                    last_reset_date = today

                if svc._swing_positions:
                    angel_client = get_angel_client()

                    # Create & start live feed once per day
                    if _live_feed is None and angel_client is not None:
                        try:
                            from data.live_feed import LiveFeed
                            _live_feed    = LiveFeed(angel_client, symbols=[])
                            _live_feed.start()
                            _feed_attached = False
                            logger.info("[SLLoop] LiveFeed started — real-time SL monitoring active.")
                        except Exception as exc:
                            logger.warning(f"[SLLoop] LiveFeed creation failed: {exc}")

                    if _live_feed is not None:
                        if not _feed_attached:
                            await svc.attach_live_feed(_live_feed)
                            _feed_attached = True
                        else:
                            # Subscribe any positions opened since last cycle
                            await svc._subscribe_open_positions()

                        triggered = await svc.check_sl_realtime()
                        if triggered:
                            logger.info(f"[SLLoop] Intraday exits triggered: {triggered}")

            else:
                # Outside market hours — stop feed, free resources
                if _live_feed is not None:
                    try:
                        _live_feed.stop()
                        logger.info("[SLLoop] LiveFeed stopped (outside market hours).")
                    except Exception:
                        pass
                    _live_feed     = None
                    _feed_attached = False

        except Exception as exc:
            logger.error(f"_swing_intraday_sl_loop error: {exc}")

        await asyncio.sleep(10)


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
# Morning broker reconnect — runs at 08:55 IST every weekday
# Ensures a fresh Angel One session 25 min before autopilot (09:20)
# and 20 min before market open (09:15).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# NiftyBees ETF autopilot — every 60s during 09:15–15:30 IST on weekdays
# ---------------------------------------------------------------------------

async def _niftybees_monitor_loop() -> None:
    """Check Nifty dip and NiftyBees position gain every 60 seconds during market hours."""
    _last_heartbeat: _date | None = None
    _last_heartbeat_hm: tuple = (0, 0)

    while True:
        try:
            now_ist    = datetime.now(_IST)
            is_weekday = now_ist.weekday() < 5
            hm         = (now_ist.hour, now_ist.minute)
            in_hours   = (9, 15) <= hm <= (15, 30)

            if is_weekday and in_hours:
                from backend.services.niftybees_service import get_niftybees_service
                from backend.dependencies import get_angel_client
                svc    = get_niftybees_service(get_angel_client())
                result = await svc.run_monitor()
                action = result.get("action", "none")

                # Always log buy/sell actions
                if action in ("bought", "sold"):
                    logger.info(f"[NiftyBeesLoop] ACTION={action} | {result.get('details', '')}")
                # Heartbeat every 30 minutes so we can verify the loop is alive in Railway logs
                elif (now_ist.hour * 60 + now_ist.minute) % 30 == 0 and hm != _last_heartbeat_hm:
                    _last_heartbeat_hm = hm
                    pos = svc._position
                    logger.info(
                        f"[NiftyBeesLoop] heartbeat {hm[0]:02d}:{hm[1]:02d} IST — "
                        f"enabled={svc._config.get('enabled')}, "
                        f"action={action}, "
                        f"detail={result.get('details', '')}, "
                        f"position={'ACTIVE (' + str(pos.get('pnl_pct', 0)) + '%)' if pos and pos.get('active') else 'none'}"
                    )
            else:
                # Outside market hours — log once per day at first check
                today = now_ist.date()
                if _last_heartbeat != today and hm >= (15, 31):
                    _last_heartbeat = today
                    logger.info(f"[NiftyBeesLoop] Market closed for today. State preserved in DB.")

        except Exception as exc:
            logger.error(f"_niftybees_monitor_loop error: {exc}")

        await asyncio.sleep(60)


async def _morning_news_loop() -> None:
    """Fetch market news at 09:00 IST Mon–Fri and cache for the day."""
    _last_fetch_date: _date | None = None

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()
            hm      = (now_ist.hour, now_ist.minute)
            is_weekday  = today.weekday() < 5
            past_cutoff = hm >= (9, 0)
            not_done_today = _last_fetch_date != today

            if is_weekday and past_cutoff and not_done_today:
                _last_fetch_date = today
                try:
                    from backend.api.routes.market_data import get_market_service, set_cached_news
                    svc   = get_market_service()
                    items = await svc.get_news_summary()
                    if items:
                        set_cached_news(items)
                        logger.info(f"[NewsLoop] Fetched {len(items)} headlines for {today}.")
                    else:
                        logger.warning("[NewsLoop] No headlines returned.")
                except Exception as exc:
                    logger.error(f"[NewsLoop] error: {exc}")
        except Exception as exc:
            logger.error(f"_morning_news_loop unexpected error: {exc}")

        await asyncio.sleep(60)


async def _session_refresh_loop() -> None:
    """
    Force a full Angel One re-login at 08:55 IST and again at 12:30 IST on trading days.
    The threading.Timer in angel_client accumulates duplicate timers on reconnect, so
    we do explicit scheduled reconnects to guarantee a live session all day.
    """
    _reconnect_slots = [(8, 55), (9, 5), (12, 30)]
    _last_dates: dict = {}   # slot-tuple → last reconnect date

    while True:
        try:
            now_ist = datetime.now(_IST)
            today   = now_ist.date()
            hm      = (now_ist.hour, now_ist.minute)

            for slot in _reconnect_slots:
                if hm >= slot and _last_dates.get(slot) != today and today.weekday() < 5:
                    _last_dates[slot] = today
                    try:
                        from backend.dependencies import get_angel_client
                        angel_client = get_angel_client()
                        if angel_client is None:
                            logger.warning(f"Session refresh {slot[0]:02d}:{slot[1]:02d} skipped — no broker client.")
                        else:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, angel_client.connect)
                            logger.info(f"Session refresh at {slot[0]:02d}:{slot[1]:02d} IST — Angel One reconnected.")
                    except Exception as exc:
                        logger.error(f"Session refresh {slot} error: {exc}")

        except Exception as exc:
            logger.error(f"_session_refresh_loop unexpected error: {exc}")

        await asyncio.sleep(60)
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


async def _startup_init_services() -> None:
    """
    Eagerly create service singletons on startup so DB state is loaded BEFORE
    the background loops fire. Retries up to 3 times (2s gaps) in case the
    Railway PostgreSQL container is still warming up.
    """
    from backend.dependencies import get_angel_client
    angel = get_angel_client()

    # --- Swing / equity service ---
    for attempt in range(3):
        try:
            from backend.api.routes.stocks import _get_svc
            svc = _get_svc()
            logger.info(
                f"[Startup] SwingService ready: {len(svc._swing_positions)} open position(s), "
                f"autopilot={'ON' if svc._autopilot_enabled else 'OFF'} "
                f"(attempt {attempt+1})"
            )
            break
        except Exception as exc:
            logger.warning(f"[Startup] SwingService init attempt {attempt+1}/3 failed: {exc}")
            if attempt < 2:
                await asyncio.sleep(3)

    # --- NiftyBees service ---
    for attempt in range(3):
        try:
            from backend.services.niftybees_service import get_niftybees_service
            nb  = get_niftybees_service(angel)
            pos = nb._position
            logger.info(
                f"[Startup] NiftyBeesService ready: "
                f"enabled={nb._config.get('enabled')}, "
                f"position={'ACTIVE (' + str(pos.get('total_qty', 0)) + ' units, avg ₹' + str(pos.get('avg_entry_price', 0)) + ')' if pos and pos.get('active') else 'none'} "
                f"(attempt {attempt+1})"
            )
            break
        except Exception as exc:
            logger.warning(f"[Startup] NiftyBeesService init attempt {attempt+1}/3 failed: {exc}")
            if attempt < 2:
                await asyncio.sleep(3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting FastAPI backend...")

    # Give Railway DB a moment to be ready on cold-start, then init singletons
    await asyncio.sleep(2)
    await _startup_init_services()

    from backend.api.routes.positions import get_position_service
    from backend.api.routes.market_data import get_market_service
    from backend.api.routes.strategies import get_strategy_service
    asyncio.create_task(
        ws_manager.start_periodic_updates(get_position_service(), get_market_service())
    )
    asyncio.create_task(_eod_squareoff_loop())
    asyncio.create_task(_morning_retrain_loop())
    asyncio.create_task(_session_refresh_loop())
    asyncio.create_task(_swing_autopilot_loop())
    asyncio.create_task(_swing_monitor_loop())
    asyncio.create_task(_swing_intraday_sl_loop())
    asyncio.create_task(_niftybees_monitor_loop())
    asyncio.create_task(_morning_news_loop())
    # Restore strategies that were running before any restart/redeploy
    await get_strategy_service().restore_running_strategies()
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
app.include_router(niftybees.router)


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
