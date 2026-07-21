"""WebSocket channels constants (re-export from redis for convenience)."""

from app.core.redis import (
    ALL_CHANNELS,
    CHANNEL_ALERTS,
    CHANNEL_DEVICES,
    CHANNEL_EVENTS,
    CHANNEL_ESTOP,
    CHANNEL_POINTCLOUD,
    CHANNEL_SCRIPT,
    CHANNEL_TASKS,
)

__all__ = [
    "ALL_CHANNELS",
    "CHANNEL_DEVICES",
    "CHANNEL_TASKS",
    "CHANNEL_ALERTS",
    "CHANNEL_POINTCLOUD",
    "CHANNEL_EVENTS",
    "CHANNEL_ESTOP",
    "CHANNEL_SCRIPT",
]
