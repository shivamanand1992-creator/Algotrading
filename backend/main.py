import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from backend.config import config
from backend.api.routes import (
    system,
    strategies,
    positions,
    trades,
    market_data,
    risk
)
from backend.dependencies import cleanup_dependencies
from backend.websocket_manager import ws_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting FastAPI backend...")
    # Lazy-import to avoid circular deps at module load time
    from backend.api.routes.positions import get_position_service
    from backend.api.routes.market_data import get_market_service
    asyncio.create_task(
        ws_manager.start_periodic_updates(get_position_service(), get_market_service())
    )
    yield
    print("Shutting down FastAPI backend...")
    cleanup_dependencies()


app = FastAPI(
    title="Algotrading API",
    description="JARVIS-style algorithmic trading platform API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(system.router)
app.include_router(strategies.router)
app.include_router(positions.router)
app.include_router(trades.router)
app.include_router(market_data.router)
app.include_router(risk.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
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
