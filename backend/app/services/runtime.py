"""Runtime services for the database-backed fleet control plane.

Robot firmware, ROS nodes and Gazebo bridges remain outside this repository.
They integrate through the HTTP gateway APIs and durable command queue.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.redis import CHANNEL_ALERTS, CHANNEL_ESTOP, CHANNEL_EVENTS, redis
from app.models.models import Alert, Device, SafetyState, Script
from app.scheduler import SchedulerEngine
from app.services.alert_engine import serialize_alert
from app.services.fleet_commands import queue_command

log = get_logger("services.runtime")
ESTOP_STATE_KEY = "safety:estop:active"

_runtime: RuntimeContext | None = None


def get_runtime() -> "RuntimeContext | None":
    return _runtime


class RuntimeContext:
    """Own scheduler and durable safety latch without generating operational data."""

    def __init__(self, app=None):
        self.app = app
        self.scheduler: SchedulerEngine | None = None
        self.estop_active = False
        self._started = False

    async def start(self) -> None:
        global _runtime
        _runtime = self

        script_id = None
        async with async_session_factory() as session:
            script = await session.scalar(select(Script).where(Script.is_active == True))
            if script:
                script_id = script.id
        await self._restore_estop_state()
        self.scheduler = SchedulerEngine(script_id)
        await self.scheduler.start()
        self._started = True
        log.info("runtime.started", data_source="gateway")

    async def stop(self) -> None:
        if self.scheduler:
            await self.scheduler.stop()
        self._started = False
        log.info("runtime.stopped")

    async def trigger_estop(self, source: str = "om") -> None:
        """Latch safety in PostgreSQL and queue a stop for each registered gateway device."""

        self.estop_active = True
        cycle_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        state = {
            "active": True,
            "source": source,
            "cycle_id": cycle_id,
            "triggered_at": timestamp.isoformat(),
        }
        async with async_session_factory() as session:
            safety = await session.get(SafetyState, "global")
            if safety is None:
                safety = SafetyState(scope="global")
                session.add(safety)
            safety.active = True
            safety.cycle_id = cycle_id
            safety.source = source
            devices = await session.execute(select(Device).where(Device.gateway_enabled == True))
            for device in devices.scalars().all():
                await queue_command(
                    session,
                    device,
                    "estop",
                    source="safety",
                    priority=100,
                    idempotency_key=f"estop:{cycle_id}:{device.id}",
                    payload={"scope": "global", "estop_cycle": cycle_id},
                )
            await session.commit()

        await redis().set(ESTOP_STATE_KEY, json.dumps(state))
        await self._publish(CHANNEL_ESTOP, {"active": True, "source": source})
        alert = await self._record_estop_alert(active=True, source=source)
        if alert:
            await self._publish(CHANNEL_ALERTS, alert)
        await self._publish(
            CHANNEL_EVENTS,
            {"time": timestamp.isoformat(), "type": "alert", "message": "Global emergency stop activated."},
        )

    async def recover_estop(self) -> None:
        """Authorize recovery and enqueue a physical release command for every device."""

        self.estop_active = False
        async with async_session_factory() as session:
            safety = await session.get(SafetyState, "global")
            if safety:
                safety.active = False
                safety.source = None
            devices = await session.execute(select(Device).where(Device.gateway_enabled == True))
            for device in devices.scalars().all():
                await queue_command(
                    session,
                    device,
                    "release",
                    source="safety",
                    priority=100,
                    idempotency_key=f"estop-release:{safety.cycle_id if safety and safety.cycle_id else 'global'}:{device.id}",
                    payload={"scope": "global", "requires_physical_safe_ack": True},
                )
            await session.commit()
        await redis().delete(ESTOP_STATE_KEY)
        await self._publish(CHANNEL_ESTOP, {"active": False})
        alert = await self._record_estop_alert(active=False)
        if alert:
            await self._publish(CHANNEL_ALERTS, alert)
        await self._publish(
            CHANNEL_EVENTS,
            {"time": datetime.now(timezone.utc).isoformat(), "type": "normal", "message": "Global emergency stop released."},
        )

    async def reload_script(self, script_id: uuid.UUID) -> None:
        if self.scheduler:
            await self.scheduler.reload(script_id)
        await self._publish(
            CHANNEL_EVENTS,
            {"time": datetime.now(timezone.utc).isoformat(), "type": "update", "message": "Active task template changed."},
        )

    async def _restore_estop_state(self) -> None:
        async with async_session_factory() as session:
            safety = await session.get(SafetyState, "global")
            if safety and safety.active:
                self.estop_active = True
                return
        raw_state = await redis().get(ESTOP_STATE_KEY)
        if raw_state:
            try:
                self.estop_active = bool(json.loads(raw_state).get("active"))
            except json.JSONDecodeError:
                log.warning("estop.restore_invalid_state")

    async def _record_estop_alert(self, active: bool, source: str | None = None) -> dict | None:
        async with async_session_factory() as session:
            alert = await session.scalar(
                select(Alert)
                .where(Alert.category == "emergency_stop", Alert.status == "open")
                .order_by(Alert.created_at.desc())
                .limit(1)
            )
            if active and alert is None:
                alert = Alert(
                    level="critical",
                    category="emergency_stop",
                    message="Global emergency stop is active.",
                    payload={"source": source},
                )
                session.add(alert)
            elif not active and alert is not None:
                alert.status = "resolved"
                alert.resolved_at = datetime.now(timezone.utc)
            else:
                return None
            await session.flush()
            await session.commit()
            return serialize_alert(alert)

    async def _publish(self, channel: str, data: dict) -> None:
        await redis().publish(channel, json.dumps({"channel": channel, "data": data}, default=str))
