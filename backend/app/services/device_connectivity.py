"""Derive a device connection state from gateway heartbeat timestamps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from app.core.config import settings

ConnectionStatus = Literal["online", "offline", "planned_offline"]


def connection_status(
    last_heartbeat: datetime | None,
    now: datetime | None = None,
    offline_reported_at: datetime | None = None,
) -> ConnectionStatus:
    """Return online, unexpected offline, or gateway-reported planned offline."""

    if offline_reported_at is not None:
        return "planned_offline"

    if last_heartbeat is None:
        return "offline"
    if last_heartbeat.tzinfo is None:
        last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    cutoff = current_time - timedelta(seconds=settings.gateway_offline_after_seconds)
    return "online" if last_heartbeat >= cutoff else "offline"


def connection_health(
    last_heartbeat: datetime | None,
    now: datetime | None = None,
    offline_reported_at: datetime | None = None,
) -> str:
    """Map connectivity to the common device health vocabulary."""

    state = connection_status(last_heartbeat, now, offline_reported_at)
    if state == "online":
        return "ok"
    if state == "planned_offline":
        return "planned_offline"
    return "fail"
