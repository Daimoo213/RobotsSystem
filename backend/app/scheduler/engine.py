"""Database-backed task scheduler for registered gateway devices."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.redis import CHANNEL_ALERTS, CHANNEL_DEVICES, CHANNEL_EVENTS, CHANNEL_TASKS, redis
from app.models.models import Device, DeviceCommand, MissionExecution, Task
from app.scheduler.dag import DAGNode, TaskDAG
from app.scheduler.market import MarketSchedulerStrategy
from app.services.alert_engine import AlertEngine
from app.services.fleet_commands import dispatch_mission, queue_command

log = get_logger("scheduler.engine")


class SchedulerEngine:
    """Allocate only registered, live devices and wait for gateway execution reports."""

    def __init__(self, script_id: uuid.UUID | None = None):
        self.strategy = MarketSchedulerStrategy()
        self.dag = TaskDAG()
        self.alert_engine = AlertEngine()
        self._task: asyncio.Task | None = None
        self._running = False
        self._script_id = script_id

    async def start(self) -> None:
        await self._load_tasks()
        self._running = True
        self._task = asyncio.create_task(self._loop())
        log.info("scheduler.started", tasks=len(self.dag.get_all_nodes()))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def reload(self, script_id: uuid.UUID) -> None:
        self._script_id = script_id
        self.dag.clear()
        await self._load_tasks()

    async def _load_tasks(self) -> None:
        async with async_session_factory() as session:
            statement = select(Task).where(Task.status.in_(["pending", "assigned", "running", "paused", "reassign_pending"]))
            if self._script_id:
                statement = statement.where(Task.script_id == self._script_id)
            tasks = (await session.execute(statement)).scalars().all()
        for task in tasks:
            self.dag.add_node(
                DAGNode(
                    task_id=str(task.id), process_id=task.process_id, name=task.name,
                    status=task.status, dependencies=task.dependencies or [],
                    device_id=str(task.device_id) if task.device_id else None,
                    priority=task.priority, map_point_id=str(task.map_point_id) if task.map_point_id else None,
                    estimated_duration=task.estimated_duration, progress=task.progress, stage=task.stage,
                )
            )

    async def _loop(self) -> None:
        while self._running:
            try:
                from app.services.runtime import get_runtime

                states = await self._get_fleet_states()
                if not (get_runtime() and get_runtime().estop_active):
                    await self._tick(states)
                await self._evaluate_safety(states)
                await self._publish(CHANNEL_DEVICES, {"devices": states})
            except Exception as exc:
                log.error("scheduler.tick_error", error=str(exc))
            await asyncio.sleep(settings.scheduler_tick_interval)

    async def _tick(self, states: list[dict]) -> None:
        await self._sync_execution_projection()
        await self._dispatch_confirmed_reassignments()
        for node in self.dag.get_ready_tasks():
            async with async_session_factory() as session:
                task = await session.get(Task, uuid.UUID(node.task_id))
                if not task or task.status != "pending" or not task.map_point_id:
                    continue
                target = await self._get_point_position(session, task)
                candidates = await self._available_candidates(session, task, target)
                winner = await self.strategy.allocate({"target_position": target}, candidates)
                if winner is None:
                    continue
                device = await session.get(Device, uuid.UUID(winner["id"]))
                if device is None:
                    continue
                execution = await dispatch_mission(session, task, device, target)
                await session.commit()
                self.dag.update_status(node.task_id, "assigned", device_id=str(device.id))
                await self._publish(CHANNEL_TASKS, {"type": "task_assigned", **_task_payload(task)})
                await self._publish(
                    CHANNEL_EVENTS,
                    {"time": datetime.now(timezone.utc).isoformat(), "type": "task_assigned", "message": f"Task {task.code} dispatched to {device.code}.", "execution_id": execution.gateway_execution_id},
                )

    async def _dispatch_confirmed_reassignments(self) -> None:
        """Dispatch a reassignment only after the previous device confirmed cancellation."""

        async with async_session_factory() as session:
            pending = await session.execute(select(Task).where(Task.status == "reassign_pending"))
            for task in pending.scalars().all():
                intent = (task.params or {}).get("pending_reassignment")
                if not intent:
                    task.status = "pending"
                    continue
                try:
                    target_device_id = uuid.UUID(str(intent["target_device_id"]))
                except (KeyError, ValueError, TypeError):
                    task.params = {key: value for key, value in (task.params or {}).items() if key != "pending_reassignment"}
                    task.status = "pending"
                    continue
                device = await session.get(Device, target_device_id)
                target = await self._get_point_position(session, task)
                candidates = await self._available_candidates(session, task, target)
                if device is None or str(device.id) not in {candidate["id"] for candidate in candidates}:
                    continue
                execution = await dispatch_mission(session, task, device, target)
                self.dag.update_status(str(task.id), "assigned", device_id=str(device.id))
                await self._publish(CHANNEL_TASKS, {"type": "task_reassigned", **_task_payload(task)})
                await self._publish(
                    CHANNEL_EVENTS,
                    {
                        "time": datetime.now(timezone.utc).isoformat(),
                        "type": "task_reassigned",
                        "message": f"Task {task.code} dispatched to {device.code} after prior mission cancellation.",
                        "execution_id": execution.gateway_execution_id,
                    },
                )
            await session.commit()

    async def _available_candidates(self, session, task: Task, target: dict[str, float]) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.gateway_offline_after_seconds)
        required_type = str(task.params.get("required_device_type") or self._required_device_type(task.process_id) or "")
        result = await session.execute(
            select(Device).where(
                Device.gateway_enabled == True,
                Device.last_heartbeat >= cutoff,
                Device.status.in_(["idle", "ready"]),
                Device.battery >= settings.low_battery_threshold,
            )
        )
        candidates = []
        for device in result.scalars().all():
            if required_type and device.type != required_type:
                continue
            processes = device.capabilities.get("processes", []) if device.capabilities else []
            if processes and task.process_id not in processes:
                continue
            candidates.append(_device_state(device))
        return candidates

    async def _sync_execution_projection(self) -> None:
        async with async_session_factory() as session:
            executions = await session.execute(
                select(MissionExecution).where(MissionExecution.state.in_(["completed", "failed", "cancelled"]))
            )
            for execution in executions.scalars().all():
                node = next((item for item in self.dag.get_all_nodes() if item.task_id == str(execution.task_id)), None)
                if node is None:
                    continue
                if execution.state == "completed" and node.status != "completed":
                    self.dag.mark_completed(node.task_id)
                    task = await session.get(Task, execution.task_id)
                    if task:
                        await self._publish(CHANNEL_TASKS, {"type": "task_completed", **_task_payload(task)})
                elif execution.state in {"failed", "cancelled"}:
                    self.dag.update_status(node.task_id, "pending" if execution.state == "cancelled" else "failed")

    async def _evaluate_safety(self, states: list[dict]) -> None:
        updates, hold_ids = await self.alert_engine.evaluate(states)
        for update in updates:
            await self._publish(CHANNEL_ALERTS, update)
        if not hold_ids:
            return
        async with async_session_factory() as session:
            for device_id in hold_ids:
                device = await session.get(Device, device_id)
                if device:
                    execution = await session.scalar(
                        select(MissionExecution)
                        .where(
                            MissionExecution.device_id == device.id,
                            MissionExecution.state.in_(["dispatched", "accepted", "running"]),
                        )
                        .order_by(MissionExecution.dispatched_at.desc())
                    )
                    if execution is not None and execution.state not in {"pause_requested", "paused"}:
                        execution.result = {
                            **(execution.result or {}),
                            "control_return_state": execution.state,
                            "safety_hold": True,
                        }
                        execution.state = "pause_requested"
                    existing = await session.scalar(
                        select(DeviceCommand.id).where(
                            DeviceCommand.device_id == device.id,
                            DeviceCommand.command == "mission_pause",
                            DeviceCommand.status.in_(["pending", "delivered"]),
                            DeviceCommand.payload["reason"].astext == "safety_rule",
                        )
                    )
                    if existing is not None:
                        continue
                    await queue_command(
                        session, device, "mission_pause", source="safety", priority=100,
                        idempotency_key=f"safety-hold:{device_id}",
                        payload={"reason": "safety_rule", "execution_id": execution.gateway_execution_id if execution else None},
                        mission_execution_id=execution.id if execution else None,
                    )
            await session.commit()

    async def _get_fleet_states(self) -> list[dict]:
        async with async_session_factory() as session:
            devices = await session.execute(select(Device).order_by(Device.code))
            return [_device_state(device) for device in devices.scalars().all()]

    async def _get_point_position(self, session, task: Task) -> dict[str, float]:
        point = task.map_point
        if point is None:
            raise ValueError("task target map point is required")
        return {"x": point.x, "y": point.y, "z": point.z}

    @staticmethod
    def _required_device_type(process_id: str) -> str | None:
        mapping = {
            "site_prep": "excavator", "pit_excavation": "excavator", "spoil_export": "agv",
            "pile_foundation": "excavator", "material_transport": "agv", "waste_removal": "agv",
            "precast_hoisting": "crane", "vertical_transport": "crane", "masonry_wall": "masonry",
            "tile_paving": "masonry", "plastering": "masonry", "safety_inspect": "inspect",
            "edge_guard": "inspect", "surveying": "inspect", "quality_check": "inspect",
        }
        return mapping.get(process_id)

    async def _publish(self, channel: str, data: dict) -> None:
        await redis().publish(channel, json.dumps({"channel": channel, "data": data}, default=str))


def _device_state(device: Device) -> dict:
    return {
        "id": str(device.id), "code": device.code, "name": device.name, "type": device.type,
        "status": device.status, "battery": device.battery,
        "position": {"x": device.position_x, "y": device.position_y, "z": device.position_z},
        "health": device.health or {},
        "operational_metrics": device.operational_metrics or {},
        "current_task": (device.operational_metrics or {}).get("current_task"),
        "task_progress": (device.operational_metrics or {}).get("task_progress"),
        "last_heartbeat": device.last_heartbeat.isoformat() if device.last_heartbeat else None,
    }


def _task_payload(task: Task) -> dict:
    device = task.__dict__.get("device")
    point = task.__dict__.get("map_point")
    return {
        "id": str(task.id), "code": task.code, "name": task.name, "process_id": task.process_id,
        "device_id": str(task.device_id) if task.device_id else None,
        "device_code": device.code if device else None, "status": task.status, "priority": task.priority,
        "map_point_id": str(task.map_point_id) if task.map_point_id else None,
        "map_point_code": point.code if point else None, "map_point_name": point.name if point else None,
        "progress": task.progress, "dependencies": task.dependencies or [], "estimated_duration": task.estimated_duration,
        "planned_start": task.planned_start.isoformat() if task.planned_start else None,
        "planned_end": task.planned_end.isoformat() if task.planned_end else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "deliverable_qty": task.deliverable_qty, "deliverable_unit": task.deliverable_unit,
        "completed_qty": task.completed_qty, "stage": task.stage, "params": task.params or {},
    }
