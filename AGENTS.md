# AGENTS.md - RIB Monitor Project Guide

## Project Overview

RIB Monitor is a Python-based network monitoring application for Juniper routers:
- **backend/**: FastAPI REST API with WebSocket support
- **tui/**: Textual-based terminal user interface  
- **shared/**: Pydantic schemas shared between components
- **tests/**: Unit tests

Uses Redis for pub/sub messaging and ARQ for async task scheduling.

## Build/Lint/Test Commands

```bash
./start.sh                                          # Start all services
docker compose up -d --build redis backend worker   # Manual start
docker compose run --rm tui                         # Run TUI interactively

python tests/test_engine.py                         # Run all tests
python -c "from tests.test_engine import test_admin_distance_flip; test_admin_distance_flip()"  # Single test
pytest tests/test_engine.py::test_admin_distance_flip -v  # With pytest

cd backend && uvicorn backend.app.api.main:app --reload --port 8000  # Backend
arq backend.app.worker.WorkerSettings                                # Worker
cd tui && python app/main.py                                         # TUI

pip install ruff mypy
ruff check .          # Lint
ruff format .         # Format
mypy backend/ tui/ shared/ --ignore-missing-imports  # Type check
```

## Code Style Guidelines

### Imports

Three groups, separated by blank lines:
1. Standard library (`import asyncio`, `from typing import List, Dict, Optional`)
2. Third-party packages (`from fastapi import FastAPI`, `import redis.asyncio as redis`)
3. Local imports (`from shared.schemas import RouteEntry`)

### Formatting

- **Line length**: 100 characters max
- **Indentation**: 4 spaces (no tabs)
- **Strings**: Double quotes preferred
- **Trailing commas**: Use in multi-line collections

### Type Hints

Use `Optional[T]` for nullable, `List[T]`/`Dict[K, V]` for collections. Prefer explicit types over `Any`.

```python
def detect_anomalies(
    self,
    previous_state: Dict[str, RouteEntry],
    current_state: Dict[str, RouteEntry],
) -> List[Anomaly]:
    ...
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `DifferenceEngine`, `RouteEntry` |
| Functions/Methods | snake_case | `detect_anomalies`, `fetch_routes` |
| Variables | snake_case | `current_state`, `route_info` |
| Constants | UPPER_SNAKE | `REDIS_HOST`, `CH_ANOMALIES` |
| Private methods | _leading_underscore | `_create_anomaly` |
| Enums | PascalCase (values UPPER) | `ProtocolType.BGP` |

### Pydantic Models (v2)

Use `model_config = ConfigDict(extra="ignore")`, `model_dump()`, `model_dump_json()`, `model_validate()`. Use Literal discriminators for discriminated unions:

```python
class RouteEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prefix: str
    table: str = "inet.0"
    optional_field: Optional[int] = None
    items: List[str] = Field(default_factory=list)

class BGPAttributes(BaseRouteAttributes):
    protocol: Literal[ProtocolType.BGP] = ProtocolType.BGP
    as_path: str

RouteAttributes = Union[BGPAttributes, OSPFAttributes, ...]
```

### Error Handling

Use `logging` module (not `print()`). Use try/except for expected errors. Silently handle non-critical errors in async loops.

```python
import logging
logger = logging.getLogger(__name__)

try:
    self.dev.open()
except Exception as e:
    logger.error(f"Failed: {e}")
finally:
    self.dev.close()
```

### Async & Configuration

```python
import os
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

async def on_mount(self) -> None:
    asyncio.create_task(self.client.listen())

async def get_initial_rib(self) -> List[RouteEntry]:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{self.base_url}/api/rib")
        return response.json()
```

### FastAPI & Textual

```python
# FastAPI
app = FastAPI(title="RIB Monitor API")

@app.get("/api/rib")
async def get_rib():
    ...

@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    ...

# Textual
class RIBMonitorApp(App):
    CSS_PATH = ["../styles/main.tcss"]
    routes = reactive([])
    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
```

### Testing

```python
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_admin_distance_flip():
    engine = DifferenceEngine()
    anomalies = engine.detect_anomalies(prev_state, current_state)
    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "ADMIN_DISTANCE_FLIP"
```

## Key Files

| File | Purpose |
|------|---------|
| `shared/schemas.py` | Pydantic models (RouteEntry, Anomaly) |
| `backend/app/core/engine.py` | Anomaly detection logic |
| `backend/app/core/poller.py` | Router polling via Junos PyEZ |
| `backend/app/api/main.py` | FastAPI endpoints and WebSocket |
| `backend/app/worker.py` | ARQ worker for scheduled polling |
| `tui/app/main.py` | Main TUI application |
| `tui/app/client.py` | HTTP/WebSocket client for backend |
