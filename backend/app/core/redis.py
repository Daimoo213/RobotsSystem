"""Redis connection + pub/sub helpers."""

from __future__ import annotations

import redis.asyncio as aioredis
from redis.asyncio.client import PubSub

from app.core.config import settings


def get_redis() -> aioredis.Redis:
    """Return a Redis client (async)."""
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        health_check_interval=30,
    )


# Module-level singleton (lazily initialised in lifespan)
redis_client: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    """Initialise the global Redis client. Call in app lifespan."""
    global redis_client
    redis_client = get_redis()
    await redis_client.ping()
    return redis_client


async def close_redis() -> None:
    """Close the global Redis client."""
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None


def redis() -> aioredis.Redis:
    """Access the global Redis client (must be initialised first)."""
    if redis_client is None:
        raise RuntimeError("Redis not initialised. Call init_redis() first.")
    return redis_client


# ── Pub/Sub channel names ────────────────────────────────
CHANNEL_DEVICES = "ws:broadcast:devices"
CHANNEL_TASKS = "ws:broadcast:tasks"
CHANNEL_ALERTS = "ws:broadcast:alerts"
CHANNEL_POINTCLOUD = "ws:broadcast:pointcloud"
CHANNEL_EVENTS = "ws:broadcast:events"
CHANNEL_ESTOP = "ws:broadcast:estop"
CHANNEL_SCRIPT = "ws:broadcast:script"

ALL_CHANNELS = [
    CHANNEL_DEVICES,
    CHANNEL_TASKS,
    CHANNEL_ALERTS,
    CHANNEL_POINTCLOUD,
    CHANNEL_EVENTS,
    CHANNEL_ESTOP,
    CHANNEL_SCRIPT,
]


async def publish(channel: str, message: str) -> None:
    """Publish a message to a Redis pub/sub channel."""
    r = redis()
    await r.publish(channel, message)


async def subscribe(channels: list[str]) -> PubSub:
    """Subscribe to Redis pub/sub channels."""
    r = redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(*channels)
    return pubsub
