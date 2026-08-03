"""Derive a device connection state from gateway heartbeat timestamps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from app.core.config import settings

ConnectionStatus = Literal["online", "offline"]


def connection_status(last_heartbeat: datetime | None, now: datetime | None = None) -> ConnectionStatus:
    """Return the live gateway connection state without inventing an operational state."""

    if last_heartbeat is None:
        return "offline"
    if last_heartbeat.tzinfo is None:
        last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    cutoff = current_time - timedelta(seconds=settings.gateway_offline_after_seconds)
    return "online" if last_heartbeat >= cutoff else "offline"


def connection_health(last_heartbeat: datetime | None, now: datetime | None = None) -> str:
    """Map connectivity to the common device health vocabulary."""

    return "ok" if connection_status(last_heartbeat, now) == "online" else "fail"
