import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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
    # Startup
    print("Starting FastAPI backend...")
    print(f"CORS origins: {config.cors_origins}")
    yield
    # Shutdown
    print("Shutting down FastAPI backend...")
    cleanup_dependencies()


# Create FastAPI app
app = FastAPI(
    title="Algotrading API",
    description="JARVIS-style algorithmic trading platform API",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(system.router)
app.include_router(strategies.router)
app.include_router(positions.router)
app.include_router(trades.router)
app.include_router(market_data.router)
app.include_router(risk.router)


@app.get("/")
async def root():
    return {
        "message": "Algotrading API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and listen for client messages
            data = await websocket.receive_text()
            # Echo back for now (can add custom handlers later)
            await websocket.send_json({
                "type": "ack",
                "message": "Message received",
                "data": data
            })
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        reload=True,
        log_level="info"
    )
