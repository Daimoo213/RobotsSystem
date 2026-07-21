"""Safety alert rules backed by the operational database."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.models import Alert, MapRegion


MANAGED_CATEGORIES = {
    "collision_risk",
    "device_fault",
    "geofence_breach",
    "low_battery",
    "device_offline",
}


@dataclass(frozen=True)
class AlertViolation:
    """A currently active condition derived from device telemetry."""

    key: str
    category: str
    level: str
    message: str
    device_id: uuid.UUID | None
    payload: dict[str, Any]
    safety_hold_device_ids: tuple[uuid.UUID, ...] = ()


def serialize_alert(alert: Alert) -> dict[str, Any]:
    """Return the single alert representation used by REST and WebSocket clients."""

    return {
        "id": str(alert.id),
        "device_id": str(alert.device_id) if alert.device_id else None,
        "level": alert.level,
        "category": alert.category,
        "message": alert.message,
        "status": alert.status,
        "payload": alert.payload or {},
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
    }


class AlertEngine:
    """Evaluate safety rules and synchronize their alert lifecycle."""

    async def evaluate(self, states: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[uuid.UUID]]:
        """Persist changed alerts and return notifications plus devices to hold."""

        async with async_session_factory() as session:
            regions = await session.execute(
                select(MapRegion).where(MapRegion.region_type == "restricted")
            )
            violations = self.derive_violations(states, regions.scalars().all())

            active_result = await session.execute(
                select(Alert).where(Alert.status.in_(["open", "ack"]))
            )
            active_alerts = active_result.scalars().all()
            active_by_key = {
                str(alert.payload.get("alert_key")): alert
                for alert in active_alerts
                if alert.category in MANAGED_CATEGORIES and alert.payload.get("alert_key")
            }

            notifications: list[Alert] = []
            current_keys = {violation.key for violation in violations}
            for violation in violations:
                if violation.key in active_by_key:
                    continue
                alert = Alert(
                    device_id=violation.device_id,
                    level=violation.level,
                    category=violation.category,
                    message=violation.message,
                    payload={"alert_key": violation.key, **violation.payload},
                )
                session.add(alert)
                notifications.append(alert)

            now = datetime.now(timezone.utc)
            for key, alert in active_by_key.items():
                if key in current_keys:
                    continue
                alert.status = "resolved"
                alert.resolved_at = now
                notifications.append(alert)

            if notifications:
                await session.flush()
                await session.commit()

        safety_holds = {
            device_id
            for violation in violations
            for device_id in violation.safety_hold_device_ids
        }
        return [serialize_alert(alert) for alert in notifications], safety_holds

    def derive_violations(
        self,
        states: list[dict[str, Any]],
        restricted_regions: list[MapRegion],
    ) -> list[AlertViolation]:
        """Derive active rule violations without performing I/O."""

        violations: list[AlertViolation] = []
        normalized = [state for state in states if _device_id(state)]

        for state in normalized:
            device_id = _device_id(state)
            if device_id is None:
                continue
            code = str(state.get("code") or device_id)
            battery = _number(state.get("battery"), default=100.0)
            health = state.get("health") or {}
            heartbeat = _parse_time(state.get("last_heartbeat"))
            if "last_heartbeat" in state and (heartbeat is None or heartbeat < datetime.now(timezone.utc) - timedelta(seconds=settings.gateway_offline_after_seconds)):
                violations.append(
                    AlertViolation(
                        key=f"device_offline:{device_id}",
                        category="device_offline",
                        level="critical",
                        message=f"Device {code} heartbeat timed out.",
                        device_id=device_id,
                        payload={"last_heartbeat": state.get("last_heartbeat"), "threshold_seconds": settings.gateway_offline_after_seconds},
                    )
                )

            if battery < settings.low_battery_threshold:
                violations.append(
                    AlertViolation(
                        key=f"low_battery:{device_id}",
                        category="low_battery",
                        level="warning",
                        message=f"Device {code} battery is below the safety threshold ({battery:.1f}%).",
                        device_id=device_id,
                        payload={"battery": battery, "threshold": settings.low_battery_threshold},
                    )
                )

            if state.get("status") == "fault" or health.get("task") == "fail":
                violations.append(
                    AlertViolation(
                        key=f"device_fault:{device_id}",
                        category="device_fault",
                        level="critical",
                        message=f"Device {code} reported a task or equipment fault.",
                        device_id=device_id,
                        payload={"status": state.get("status"), "health": health},
                    )
                )

            position = _position(state)
            for region in restricted_regions:
                if position and _point_in_polygon(position, region.polygon or []):
                    active_motion = state.get("status") in {"moving", "working"}
                    violations.append(
                        AlertViolation(
                            key=f"geofence_breach:{device_id}:{region.id}",
                            category="geofence_breach",
                            level="critical",
                            message=f"Device {code} entered restricted region {region.code}.",
                            device_id=device_id,
                            payload={"region_id": str(region.id), "region_code": region.code, "position": position},
                            safety_hold_device_ids=(device_id,) if active_motion else (),
                        )
                    )

        active_states = [
            state
            for state in normalized
            if state.get("status") in {"moving", "working"} and _position(state)
        ]
        for left, right in combinations(active_states, 2):
            left_id = _device_id(left)
            right_id = _device_id(right)
            left_position = _position(left)
            right_position = _position(right)
            if not left_id or not right_id or not left_position or not right_position:
                continue

            distance = math.dist(left_position, right_position)
            if distance >= settings.device_safety_distance:
                continue

            ordered_ids = sorted((left_id, right_id), key=str)
            left_code = str(left.get("code") or left_id)
            right_code = str(right.get("code") or right_id)
            violations.append(
                AlertViolation(
                    key=f"collision_risk:{ordered_ids[0]}:{ordered_ids[1]}",
                    category="collision_risk",
                    level="critical",
                    message=(
                        f"Devices {left_code} and {right_code} are {distance:.2f}m apart, "
                        f"below the {settings.device_safety_distance:.2f}m safety distance."
                    ),
                    device_id=left_id,
                    payload={
                        "peer_device_id": str(right_id),
                        "distance": round(distance, 3),
                        "threshold": settings.device_safety_distance,
                    },
                    safety_hold_device_ids=(left_id, right_id),
                )
            )

        return violations


def _device_id(state: dict[str, Any]) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(state.get("id")))
    except (TypeError, ValueError):
        return None


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _position(state: dict[str, Any]) -> tuple[float, float] | None:
    raw_position = state.get("position")
    if not isinstance(raw_position, dict):
        return None
    try:
        return float(raw_position["x"]), float(raw_position["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    """Return whether a point lies inside a simple two-dimensional polygon."""

    if len(polygon) < 3:
        return False

    x, y = point
    inside = False
    previous_x, previous_y = polygon[-1]
    for current_x, current_y in polygon:
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            boundary_x = (previous_x - current_x) * (y - current_y) / (previous_y - current_y) + current_x
            if x < boundary_x:
                inside = not inside
        previous_x, previous_y = current_x, current_y
    return inside
