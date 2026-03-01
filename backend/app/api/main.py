import asyncio
import os
import json
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import redis.asyncio as redis

from shared.schemas import ConnectionConfig

# Setup logging first
from backend.app.core.logging_config import get_logger, setup_logging

setup_logging(level="DEBUG")
logger = get_logger(__name__)

logger.info("Starting RIB Monitor API...")

# Config
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}")

app = FastAPI(title="RIB Monitor API")

# Redis connection
redis_client = redis.from_url(
    f"redis://{REDIS_HOST}:{REDIS_PORT}", decode_responses=True
)

# Global connection engine reference
_current_connection = None

# Import connection engines after logging is setup
from backend.app.core.connection_engine import ConnectionEngine
from backend.app.core.disconnect_engine import DisconnectEngine


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        logger.debug("ConnectionManager initialized")

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(
                f"WebSocket disconnected. Total: {len(self.active_connections)}"
            )

    async def broadcast(self, message: str):
        logger.debug(f"Broadcasting to {len(self.active_connections)} clients")
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")


manager = ConnectionManager()


@app.on_event("startup")
async def startup_event():
    logger.info("API startup - starting Redis connector")
    asyncio.create_task(redis_connector())


async def redis_connector():
    """
    Subscribes to Redis channels and broadcasts to WS clients.
    """
    logger.info("Redis connector starting...")
    pubsub = redis_client.pubsub()

    try:
        await pubsub.subscribe("rib:anomalies", "rib:routes")
        logger.info("Subscribed to Redis channels: rib:anomalies, rib:routes")
    except Exception as e:
        logger.error(f"Failed to subscribe to Redis: {e}")
        return

    async for message in pubsub.listen():
        if message["type"] == "message":
            payload = {"channel": message["channel"], "data": message["data"]}
            logger.debug(f"Redis message on {message['channel']}")
            await manager.broadcast(json.dumps(payload))


@app.get("/api/rib")
async def get_rib():
    logger.debug("GET /api/rib")
    try:
        data = await redis_client.get("rib:latest")
        if data:
            logger.debug(f"Returning {len(json.loads(data))} routes")
            return json.loads(data)
    except Exception as e:
        logger.error(f"Error getting RIB: {e}")
    return []


@app.post("/api/connect")
async def connect_router(config: ConnectionConfig):
    """
    Connects to the router and validates the connection before saving config.
    """
    global _current_connection

    logger.info("=" * 60)
    logger.info("CONNECT REQUEST RECEIVED")
    logger.info(f"  Host: {config.host}")
    logger.info(f"  User: {config.user}")
    logger.info(f"  Port: {config.port}")
    logger.info("=" * 60)

    # Disconnect any existing connection
    if _current_connection:
        logger.info("Disconnecting from previous device...")
        try:
            disconnect_engine = DisconnectEngine(_current_connection)
            disconnect_engine.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting previous: {e}")

    # Create new connection engine
    logger.info("Creating new ConnectionEngine...")
    connection_engine = ConnectionEngine(
        host=config.host,
        user=config.user,
        password=config.password,
        port=config.port,
    )

    # Test the connection
    logger.info("Attempting connection...")

    try:
        if not connection_engine.connect():
            logger.error(f"Connection failed to {config.host}")
            return {
                "status": "error",
                "message": f"Failed to connect to {config.host}. Check logs for details.",
            }
    except Exception as e:
        logger.error(f"Connection exception: {e}", exc_info=True)
        return {"status": "error", "message": f"Connection error: {str(e)}"}

    # Connection successful
    _current_connection = connection_engine

    # Save config to Redis
    config_dict = config.model_dump()
    await redis_client.set("rib:config", json.dumps(config_dict))
    logger.info("Connection config saved to Redis")

    # Get device info
    conn_info = connection_engine.get_connection_info()
    device_info = conn_info.device_info if conn_info else {}

    logger.info("=" * 60)
    logger.info("CONNECTION SUCCESSFUL!")
    logger.info(f"  Host: {config.host}")
    logger.info(f"  Device: {device_info.get('hostname', 'N/A')}")
    logger.info("=" * 60)

    # Notify worker
    await redis_client.publish("rib:routes", "RECONNECT")

    return {
        "status": "connected",
        "message": f"Connected to {config.host}",
        "device_info": device_info,
    }


@app.post("/api/disconnect")
async def disconnect_router():
    """
    Disconnects from the current router.
    """
    global _current_connection

    logger.info("DISCONNECT REQUEST RECEIVED")

    if not _current_connection:
        logger.info("No active connection to disconnect")
        return {"status": "not_connected", "message": "No active connection"}

    logger.info(f"Disconnecting from {_current_connection.host}...")

    try:
        disconnect_engine = DisconnectEngine(_current_connection)
        success = disconnect_engine.disconnect()

        if success:
            _current_connection = None
            await redis_client.delete("rib:config")
            await redis_client.delete("rib:latest")
            logger.info("Successfully disconnected")
            return {"status": "disconnected", "message": "Disconnected successfully"}
        else:
            logger.error("Disconnect returned false")
            return {"status": "error", "message": "Error during disconnect"}

    except Exception as e:
        logger.error(f"Disconnect error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.get("/api/config")
async def get_config():
    logger.debug("GET /api/config")
    try:
        config_data = await redis_client.get("rib:config")
        if config_data:
            return json.loads(config_data)
    except Exception as e:
        logger.error(f"Error getting config: {e}")
    return None


@app.get("/api/status")
async def get_status():
    """Get current connection status."""
    logger.debug("GET /api/status")

    if _current_connection and _current_connection.is_connected:
        conn_info = _current_connection.get_connection_info()
        return {
            "connected": True,
            "host": _current_connection.host,
            "device_info": conn_info.device_info if conn_info else {},
        }

    return {"connected": False}


@app.post("/api/fetch-rib")
async def fetch_rib():
    """
    Fetch routing table from connected device and save to rib-data folder.
    """
    global _current_connection

    if not _current_connection or not _current_connection.is_connected:
        return {"status": "error", "message": "Not connected to any device"}

    logger.info("Fetching RIB from device...")

    try:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        def _fetch_sync():
            from shared.get_rib import get_rib_pyez, save_rib
            from pathlib import Path

            conn_info = _current_connection.get_connection_info()
            hostname = (
                conn_info.device_info.get("hostname", _current_connection.host)
                if conn_info
                else _current_connection.host
            )

            # Get the device from connection engine
            dev = _current_connection.device
            if not dev:
                return {"error": "Device not available"}

            # Retrieve routes using RPC
            routes = []
            try:
                route_info = dev.rpc.get_route_information(
                    table="inet.0", extensive=True
                )

                for route_entry in route_info.xpath(".//rt-entry"):
                    route_data = {
                        "prefix": "",
                        "table": "inet.0",
                        "protocol": "Unknown",
                        "next_hop": "",
                        "age": 0,
                        "preference": 0,
                        "metric": 0,
                        "active": False,
                    }

                    dest = route_entry.getparent()
                    if dest is not None:
                        rt_dest = dest.find("rt-destination")
                        if rt_dest is not None:
                            route_data["prefix"] = rt_dest.text or ""

                    proto = route_entry.find("protocol-name")
                    if proto is not None:
                        route_data["protocol"] = proto.text or "Unknown"

                    active_tag = route_entry.find("active-tag")
                    if active_tag is not None:
                        route_data["active"] = active_tag.text == "*"

                    nh = route_entry.find(".//nh")
                    if nh is not None:
                        via = nh.find("via")
                        if via is not None:
                            route_data["next_hop"] = via.text or ""
                        to = nh.find("to")
                        if to is not None and not route_data["next_hop"]:
                            route_data["next_hop"] = to.text or ""

                    pref = route_entry.find("preference")
                    if pref is not None:
                        try:
                            route_data["preference"] = int(pref.text or 0)
                        except ValueError:
                            pass

                    metric = route_entry.find("metric")
                    if metric is not None:
                        try:
                            route_data["metric"] = int(metric.text or 0)
                        except ValueError:
                            pass

                    if route_data["prefix"]:
                        routes.append(route_data)

            except Exception as e:
                logger.error(f"Error fetching routes: {e}")
                return {"error": str(e)}

            # Prepare data
            data = {
                "device": _current_connection.host,
                "hostname": hostname,
                "timestamp": datetime.now().isoformat(),
                "routes": routes,
                "total_routes": len(routes),
            }

            # Save to file
            output_dir = Path("/app/rib-data")
            output_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = f"{hostname}_rib_{timestamp}"
            json_path = output_dir / f"{base_name}.json"

            import json

            with open(json_path, "w") as f:
                json.dump(data, f, indent=2, default=str)

            return {"file": str(json_path), "routes": len(routes), "hostname": hostname}

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            result = await loop.run_in_executor(executor, _fetch_sync)

        if "error" in result:
            return {"status": "error", "message": result["error"]}

        logger.info(f"RIB saved to {result['file']}")

        return {
            "status": "success",
            "message": f"Saved {result['routes']} routes to {result['file']}",
            "file": result["file"],
            "routes": result["routes"],
            "hostname": result["hostname"],
        }

    except Exception as e:
        logger.error(f"Error fetching RIB: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send current state on connection
        latest_rib = await redis_client.get("rib:latest")
        if latest_rib:
            await websocket.send_text(
                json.dumps({"channel": "rib:initial", "data": json.loads(latest_rib)})
            )

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
