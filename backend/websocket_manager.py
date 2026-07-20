import asyncio
import json
from typing import List, Set
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))


class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.broadcast_task = None

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"WebSocket client connected. Total connections: {len(self.active_connections)}")

        # Send initial state
        await self.send_personal_message(
            {
                "type": "connected",
                "message": "Connected to trading platform",
                "timestamp": datetime.now().isoformat()
            },
            websocket
        )

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        print(f"WebSocket client disconnected. Total connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send message to a specific client"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            print(f"Error sending message to client: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        msg_type = message.get("type", "unknown")
        msg_action = message.get("action", message.get("data", {}).get("type", "N/A"))
        print(f"📡 Broadcasting: type={msg_type}, action={msg_action}, clients={len(self.active_connections)}")

        disconnected = []
        json_str = json.dumps(message, default=str)
        for connection in self.active_connections:
            try:
                await connection.send_text(json_str)
            except Exception as e:
                print(f"Error broadcasting to client: {e}")
                disconnected.append(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_position_update(self, positions: list):
        """Broadcast position updates"""
        await self.broadcast({
            "type": "position_update",
            "data": {
                "positions": positions,
                "timestamp": datetime.now().isoformat()
            }
        })

    async def broadcast_market_tick(self, tick_data: dict):
        """Broadcast market tick data"""
        await self.broadcast({
            "type": "market_tick",
            "data": tick_data
        })

    async def broadcast_signal(self, signal: dict):
        """Broadcast new trading signal"""
        await self.broadcast({
            "type": "new_signal",
            "data": signal
        })

    async def broadcast_risk_alert(self, alert: dict):
        """Broadcast risk alert"""
        await self.broadcast({
            "type": "risk_alert",
            "data": alert
        })

    async def start_periodic_updates(self, position_service, market_service):
        """Start periodic data broadcasting"""
        while True:
            try:
                if len(self.active_connections) > 0:
                    # Broadcast position updates every 5 seconds
                    positions = await position_service.get_all_positions()
                    await self.broadcast_position_update(
                        [pos.dict() for pos in positions]
                    )

                    # Broadcast market data
                    market_data = await market_service.get_current_market_data()
                    await self.broadcast_market_tick(market_data.dict())

                await asyncio.sleep(5)
            except Exception as e:
                print(f"Error in periodic updates: {e}")
                await asyncio.sleep(5)


# Global WebSocket manager instance
ws_manager = WebSocketManager()
