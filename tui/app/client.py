import asyncio
import json
import httpx
import websockets
from typing import Callable, List, Optional
from shared.schemas import RouteEntry, Anomaly, ConnectionConfig


class RIBClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.ws_url = f"ws://{base_url.split('://')[1]}/ws/stream"
        self.on_anomaly: Optional[Callable[[Anomaly], None]] = None
        self.on_refresh: Optional[Callable[[List[RouteEntry]], None]] = None
        self.on_ws_status: Optional[Callable[[bool, Optional[str]], None]] = None
        self._ws = None
        self._listening = False

    async def get_initial_rib(self) -> List[RouteEntry]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(f"{self.base_url}/api/rib")
                if response.status_code == 200:
                    data = response.json()
                    return [RouteEntry(**r) for r in data]
            except Exception as e:
                print(f"Error getting RIB: {e}")
            return []

    async def get_config(self) -> Optional[dict]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(f"{self.base_url}/api/config")
                if response.status_code == 200:
                    return response.json()
            except Exception:
                pass
            return None

    async def get_status(self) -> dict:
        """Get connection status from backend."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(f"{self.base_url}/api/status")
                if response.status_code == 200:
                    return response.json()
            except Exception:
                pass
            return {"connected": False}

    async def connect_router(self, config: ConnectionConfig) -> bool:
        """Connect to a router via the backend API."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/connect", json=config.model_dump()
                )
                if response.status_code == 200:
                    result = response.json()
                    # Check if connection was successful
                    return result.get("status") == "connected"
                return False
            except Exception as e:
                print(f"Connection error: {e}")
                return False

    async def disconnect_router(self) -> bool:
        """Disconnect from the current router."""
        self._listening = False

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(f"{self.base_url}/api/disconnect")
                if response.status_code == 200:
                    result = response.json()
                    return result.get("status") == "disconnected"
            except Exception as e:
                print(f"Disconnect error: {e}")
            return False

    async def fetch_rib(self) -> dict:
        """Fetch routing table from connected device and save to rib-data."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(f"{self.base_url}/api/fetch-rib")
                if response.status_code == 200:
                    return response.json()
            except Exception as e:
                print(f"Fetch RIB error: {e}")
                return {"status": "error", "message": str(e)}
        return {"status": "error", "message": "Unknown error"}

    async def listen(self):
        """Connect to WebSocket and listen for events."""
        retry_count = 0
        max_retries = 5
        self._listening = True

        while retry_count < max_retries and self._listening:
            try:
                if self.on_ws_status:
                    self.on_ws_status(True)

                async with websockets.connect(
                    self.ws_url, ping_interval=20, ping_timeout=10
                ) as ws:
                    self._ws = ws
                    retry_count = 0

                    while self._listening:
                        try:
                            msg = await ws.recv()
                            payload = json.loads(msg)
                            channel = payload.get("channel")
                            data = payload.get("data")

                            if channel == "rib:anomalies":
                                if self.on_anomaly:
                                    anomaly_data = (
                                        json.loads(data)
                                        if isinstance(data, str)
                                        else data
                                    )
                                    self.on_anomaly(Anomaly(**anomaly_data))
                            elif channel == "rib:routes":
                                routes = await self.get_initial_rib()
                                if self.on_refresh:
                                    self.on_refresh(routes)
                            elif channel == "rib:initial":
                                if self.on_refresh:
                                    self.on_refresh([RouteEntry(**r) for r in data])

                        except websockets.exceptions.ConnectionClosed:
                            break

            except Exception as e:
                retry_count += 1
                if self.on_ws_status:
                    self.on_ws_status(False, str(e))

                if retry_count < max_retries and self._listening:
                    await asyncio.sleep(5)
                else:
                    self._ws = None
                    break

    def stop_listening(self):
        """Stop the WebSocket listener."""
        self._listening = False
