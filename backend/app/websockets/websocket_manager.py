import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis
from backend.app.config import settings

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

manager = ConnectionManager()

async def listen_to_redis_channel(analysis_id: str, websocket: WebSocket):
    """Subscribe to a Redis channel for the analysis ID and stream messages to the WebSocket client.
    
    When the analysis completes or fails, the WebSocket is closed after sending the final
    message so the frontend can fall back to HTTP polling.
    """
    import json as _json
    r = aioredis.from_url(settings.REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
    pubsub = r.pubsub()
    channel = f"analysis_progress_{analysis_id}"
    try:
        await pubsub.subscribe(channel)
    except Exception as exc:
        await websocket.send_text(_json.dumps({"progress": 0, "status": "degraded", "message": f"Redis progress stream unavailable: {exc}", "files_analyzed": 0, "total_files": 0, "current_file": ""}))
        await websocket.close()
        await r.close()
        return
    
    try:
        last_heartbeat = 0.0
        while True:
            # Check for new messages from Redis
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message["type"] == "message":
                data = message["data"].decode("utf-8")
                await websocket.send_text(data)
                
                # If analysis completed or failed, close WebSocket so the frontend
                # onclose handler triggers and falls back to HTTP polling properly.
                data_dict = _json.loads(data)
                if data_dict.get("progress") == 100 or "failed" in data_dict.get("status", "").lower():
                    await websocket.close()
                    break
                last_heartbeat = now  # Reset heartbeat timer after real message
            
            # Send heartbeat every ~6s only if no progress message arrived
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= 5.0:
                try:
                    await websocket.send_text(_json.dumps({"type": "heartbeat"}))
                    last_heartbeat = now
                except Exception:
                    break
            await asyncio.sleep(0.1)  # Small sleep to yield control
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"Error in WebSocket Redis listener: {e}")
    finally:
        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            pass
        try:
            await r.close()
        except Exception:
            pass

