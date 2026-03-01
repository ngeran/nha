import asyncio
import json
import os
import logging
from typing import Dict
from arq import create_pool
from arq.connections import RedisSettings
import redis.asyncio as redis

from shared.schemas import RouteEntry, Anomaly
from backend.app.core.poller import RIBEngine
from backend.app.core.engine import DifferenceEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROUTER_HOST = os.getenv("ROUTER_HOST", "router.example.com")
ROUTER_USER = os.getenv("ROUTER_USER", "admin")
ROUTER_PASS = os.getenv("ROUTER_PASS", "password")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

CH_ANOMALIES = "rib:anomalies"
CH_ROUTES = "rib:routes"


async def startup(ctx):
    logger.info("Starting up RIB Monitor Worker...")
    ctx["engine"] = DifferenceEngine()
    ctx["redis"] = redis.from_url(f"redis://{REDIS_HOST}:{REDIS_PORT}")
    ctx["prev_state"] = {}


async def shutdown(ctx):
    logger.info("Shutting down RIB Monitor Worker...")
    await ctx["redis"].close()


async def poll_router_task(ctx):
    """
    Main polling loop.
    """
    r = ctx["redis"]

    config_data = await r.get("rib:config")
    if not config_data:
        logger.warning("No router config found in Redis. Skipping poll.")
        return

    from shared.schemas import ConnectionConfig

    config = ConnectionConfig.model_validate_json(config_data)

    rib_engine = RIBEngine(
        host=config.host, user=config.user, password=config.password, port=config.port
    )

    engine = ctx["engine"]
    prev_state = ctx["prev_state"]

    logger.info(f"Polling router {config.host}...")
    current_routes = rib_engine.fetch_routes()

    current_state = {f"{r.prefix}:{r.table}:{r.protocol}": r for r in current_routes}

    anomalies = engine.detect_anomalies(prev_state, current_state)

    for anomaly in anomalies:
        logger.warning(f"Anomaly detected: {anomaly.message}")
        await r.publish(CH_ANOMALIES, anomaly.model_dump_json())

    await r.set("rib:latest", json.dumps([r.model_dump() for r in current_routes]))
    await r.publish(CH_ROUTES, "UPDATE")

    ctx["prev_state"] = current_state


import arq


class WorkerSettings:
    functions = [poll_router_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings(host=REDIS_HOST, port=REDIS_PORT)
    cron_jobs = [
        arq.cron(poll_router_task, second=0, minute="*", hour="*", run_at_startup=True)
    ]
