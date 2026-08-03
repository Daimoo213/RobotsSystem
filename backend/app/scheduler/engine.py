"""Database-backed task scheduler for registered gateway devices."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.redis import CHANNEL_ALERTS, CHANNEL_DEVICES, CHANNEL_EVENTS, CHANNEL_TASKS, redis
from app.models.models import Device, DeviceCommand, MissionExecution, Task, TaskResourceAllocation
from app.scheduler.dag import DAGNode, TaskDAG
from app.scheduler.market import MarketSchedulerStrategy
from app.scheduler.matching import PROCESS_DEVICE_TYPES, device_is_compatible
from app.scheduler.resource_planner import plan_task_resources
from app.scheduler.scheduling import completed_dependency_anchor
from app.services.alert_engine import AlertEngine
from app.services.device_connectivity import connection_health, connection_status
from app.services.fleet_commands import build_mission_navigation, dispatch_mission, queue_command

log = get_logger("scheduler.engine")

ACTIVE_EXECUTION_STATES = (
    "dispatched",
    "accepted",
    "running",
    "paused",
    "pause_requested",
    "resume_requested",
    "cancel_requested",
)
SCHEDULER_TASK_STATES = ("pending", "assigned", "running", "paused", "reassign_pending", "failed")
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
        await self._sync_task_dag()

    async def _sync_task_dag(self) -> None:
        """Rebuild the scheduling view from the database so restarts cannot lose work."""

        async with async_session_factory() as session:
            active_scope = Task.status.in_(SCHEDULER_TASK_STATES)
            if self._script_id:
                active_scope = active_scope & (Task.script_id == self._script_id)
            statement = select(Task).where(or_(Task.status == "completed", active_scope))
            tasks = (await session.execute(statement)).scalars().all()
        self.dag.clear()
        for task in tasks:
            self.dag.add_node(
                DAGNode(
                    task_id=str(task.id), process_id=task.process_id, name=task.name,
                    status=task.status, dependencies=task.dependencies or [],
                    device_id=str(task.device_id) if task.device_id else None,
                    priority=task.priority, map_point_id=str(task.map_point_id) if task.map_point_id else None,
                    estimated_duration=task.estimated_duration, progress=task.progress, stage=task.stage,
                    planned_start=task.planned_start,
                )
            )

    async def _loop(self) -> None:
        while self._running:
            try:
                from app.services.runtime import get_runtime

                await self._sync_device_connectivity()
                states = await self._get_fleet_states()
                await self._evaluate_safety(states)
                if not (get_runtime() and get_runtime().estop_active):
                    await self._tick(states)
                await self._publish(CHANNEL_DEVICES, {"devices": states})
            except Exception as exc:
                log.error("scheduler.tick_error", error=str(exc))
            await asyncio.sleep(settings.scheduler_tick_interval)

    async def _sync_device_connectivity(self) -> None:
        """Project heartbeat expiry into persisted health for REST and audit consumers."""

        async with async_session_factory() as session:
            devices = await session.execute(select(Device).where(Device.gateway_enabled == True))
            changed = False
            for device in devices.scalars().all():
                health = dict(device.health or {})
                expected_health = connection_health(device.last_heartbeat)
                if health.get("connection") == expected_health:
                    continue
                device.health = {**health, "connection": expected_health}
                changed = True
            if changed:
                await session.commit()

    async def _tick(self, states: list[dict]) -> None:
        await self._refresh_completed_dependency_schedules()
        await self._sync_task_dag()
        await self._sync_dependency_waiting_states()
        await self._dispatch_confirmed_reassignments()
        for node in self.dag.get_ready_tasks():
            async with async_session_factory() as session:
                task = await session.scalar(
                    select(Task)
                    .options(selectinload(Task.map_point), selectinload(Task.return_point))
                    .where(Task.id == uuid.UUID(node.task_id), Task.status.in_(("pending", "assigned", "running")))
                    .with_for_update(skip_locked=True)
                )
                if not task or not task.map_point_id:
                    continue
                now_at = datetime.now(timezone.utc)
                decision = await plan_task_resources(session, task, at=now_at)
                if task.planned_start and task.planned_start > now_at:
                    changed = self._set_dispatch_waiting(task, "waiting_schedule", "planned_start_not_reached")
                    await session.commit()
                    if changed:
                        await self._publish(CHANNEL_TASKS, {"type": "task_waiting", **_task_payload(task)})
                    continue
                if not decision.is_sufficient:
                    state = "waiting_planning_input" if decision.state == "waiting_planning_input" else "waiting_capacity"
                    changed = self._set_dispatch_waiting(task, state, decision.reason or "insufficient_capacity")
                    await session.commit()
                    if changed:
                        await self._publish(CHANNEL_TASKS, {"type": "task_waiting", **_task_payload(task)})
                    continue
                if not decision.proposals:
                    await session.commit()
                    continue

                proposal_device_ids = sorted({proposal.device.id for proposal in decision.proposals}, key=str)
                locked_devices = (
                    await session.execute(
                        select(Device).where(Device.id.in_(proposal_device_ids)).with_for_update(skip_locked=True)
                    )
                ).scalars().all()
                device_by_id = {device.id: device for device in locked_devices}
                devices_still_available = len(device_by_id) == len(proposal_device_ids)
                if devices_still_available:
                    for proposal in decision.proposals:
                        if not await self._device_is_still_available(session, task, device_by_id[proposal.device.id]):
                            devices_still_available = False
                            break
                if not devices_still_available:
                    changed = self._set_dispatch_waiting(task, "waiting_capacity", "compatible_devices_busy")
                    await session.commit()
                    if changed:
                        await self._publish(CHANNEL_TASKS, {"type": "task_waiting", **_task_payload(task)})
                    continue
                task.dispatch_attempts += 1
                task.last_dispatch_attempt_at = now_at
                target, return_plan = await build_mission_navigation(session, task)
                try:
                    executions = []
                    next_revision = decision.plan.revision + 1
                    for proposal in decision.proposals:
                        allocation = TaskResourceAllocation(
                            task_id=task.id,
                            requirement_id=proposal.requirement.id,
                            requirement=proposal.requirement,
                            device_id=proposal.device.id,
                            plan_revision=next_revision,
                            planned_qty=proposal.planned_qty,
                            output_unit=proposal.requirement.output_unit,
                            rate_per_hour_snapshot=proposal.capacity.rate_per_hour,
                            capacity_source=proposal.capacity.source,
                            capacity_evidence_ref=proposal.capacity.evidence_ref,
                            capacity_reported_at=proposal.capacity.reported_at,
                            work_scope=proposal.requirement.work_scope or {},
                            available_from=proposal.available_from,
                            predicted_finish_at=proposal.predicted_finish_at,
                            state="planned",
                        )
                        session.add(allocation)
                        await session.flush()
                        execution = await dispatch_mission(
                            session,
                            task,
                            device_by_id[proposal.device.id],
                            target,
                            return_plan,
                            allocation=allocation,
                        )
                        executions.append(execution)
                    decision.plan.revision = next_revision
                    decision.plan.state = "dispatched"
                    decision.plan.reason = None
                    task.status = "assigned"
                    task.device_id = device_by_id[decision.proposals[0].device.id].id
                    task.dispatch_state = "dispatched"
                    task.dispatch_reason = None
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    log.info("scheduler.dispatch_conflict", task_id=node.task_id)
                    continue
                self.dag.update_status(node.task_id, "assigned", device_id=str(task.device_id))
                await self._publish(CHANNEL_TASKS, {"type": "task_assigned", **_task_payload(task)})
                await self._publish(
                    CHANNEL_EVENTS,
                    {
                        "time": datetime.now(timezone.utc).isoformat(),
                        "type": "task_assigned",
                        "message": f"任务 {task.code} 已派发给 {len(executions)} 台设备执行。",
                        "execution_ids": [execution.gateway_execution_id for execution in executions],
                    },
                )

    async def _sync_dependency_waiting_states(self) -> None:
        ready_ids = {node.task_id for node in self.dag.get_ready_tasks()}
        blocked_ids = [
            uuid.UUID(node.task_id)
            for node in self.dag.get_all_nodes()
            if node.status == "pending" and node.task_id not in ready_ids and node.dependencies
        ]
        if not blocked_ids:
            return
        changed_tasks: list[Task] = []
        async with async_session_factory() as session:
            tasks = (await session.execute(select(Task).where(Task.id.in_(blocked_ids)))).scalars().all()
            dependency_ids = {
                uuid.UUID(dependency_id)
                for task in tasks
                for dependency_id in (task.dependencies or [])
                if _is_uuid(dependency_id)
            }
            dependency_rows = (
                await session.execute(select(Task).where(Task.id.in_(dependency_ids)))
                if dependency_ids
                else None
            )
            dependencies_by_id = {
                str(dependency.id): dependency
                for dependency in (dependency_rows.scalars().all() if dependency_rows is not None else [])
            }
            for task in tasks:
                statuses = [dependencies_by_id.get(str(dependency_id)).status if dependencies_by_id.get(str(dependency_id)) else "missing" for dependency_id in (task.dependencies or [])]
                if "cancelled" in statuses:
                    reason = "dependency_cancelled"
                elif "failed" in statuses:
                    reason = "dependency_failed"
                elif "missing" in statuses:
                    reason = "dependency_missing"
                else:
                    reason = "dependencies_incomplete"
                if self._set_dispatch_waiting(task, "waiting_dependencies", reason):
                    changed_tasks.append(task)
            if changed_tasks:
                await session.commit()
        for task in changed_tasks:
            await self._publish(CHANNEL_TASKS, {"type": "task_waiting", **_task_payload(task)})

    async def _refresh_completed_dependency_schedules(self) -> None:
        """Replace a dependency forecast with actual predecessor completion time."""

        updated_tasks: list[Task] = []
        async with async_session_factory() as session:
            candidates = (
                await session.execute(
                    select(Task).where(Task.status == "pending", Task.schedule_mode == "auto")
                )
            ).scalars().all()
            candidates = [task for task in candidates if task.dependencies]
            dependency_ids = {
                uuid.UUID(dependency_id)
                for task in candidates
                for dependency_id in task.dependencies
                if _is_uuid(dependency_id)
            }
            if not dependency_ids:
                return
            dependencies = (
                await session.execute(select(Task).where(Task.id.in_(dependency_ids)))
            ).scalars().all()
            dependencies_by_id = {str(dependency.id): dependency for dependency in dependencies}
            for task in candidates:
                predecessor_rows = [dependencies_by_id.get(str(dependency_id)) for dependency_id in task.dependencies]
                if any(predecessor is None for predecessor in predecessor_rows):
                    continue
                anchor = completed_dependency_anchor(predecessor for predecessor in predecessor_rows if predecessor is not None)
                if anchor is None:
                    continue
                anchor_value = anchor.isoformat()
                params = dict(task.params or {})
                if params.get("auto_schedule_anchor") == anchor_value:
                    continue
                task.planned_start = anchor
                task.planned_end = anchor + timedelta(minutes=task.estimated_duration)
                task.params = {**params, "auto_schedule_anchor": anchor_value}
                await plan_task_resources(session, task, at=datetime.now(timezone.utc))
                updated_tasks.append(task)
            if updated_tasks:
                await session.commit()
        for task in updated_tasks:
            await self._publish(CHANNEL_TASKS, {"type": "task_schedule_updated", **_task_payload(task)})

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
                target, return_plan = await build_mission_navigation(session, task)
                candidates, waiting_reason = await self._available_candidates(session, task, target)
                if device is None or str(device.id) not in {candidate["id"] for candidate in candidates}:
                    self._set_dispatch_waiting(task, "waiting_device", waiting_reason)
                    continue
                execution = await dispatch_mission(session, task, device, target, return_plan)
                self.dag.update_status(str(task.id), "assigned", device_id=str(device.id))
                await self._publish(CHANNEL_TASKS, {"type": "task_reassigned", **_task_payload(task)})
                await self._publish(
                    CHANNEL_EVENTS,
                    {
                        "time": datetime.now(timezone.utc).isoformat(),
                        "type": "task_reassigned",
                        "message": f"旧设备已确认取消，任务 {task.code} 已改派给设备 {device.code}。",
                        "execution_id": execution.gateway_execution_id,
                    },
                )
            await session.commit()

    async def _available_candidates(
        self,
        session,
        task: Task,
        target: dict[str, float],
    ) -> tuple[list[dict], str]:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.gateway_offline_after_seconds)
        devices = (
            await session.execute(select(Device).where(Device.gateway_enabled == True).order_by(Device.code))
        ).scalars().all()
        if not devices:
            return [], "no_enabled_device"
        active_device_ids = set(
            (
                await session.execute(
                    select(MissionExecution.device_id).where(MissionExecution.state.in_(ACTIVE_EXECUTION_STATES))
                )
            ).scalars().all()
        )
        compatible = [device for device in devices if device_is_compatible(task, device)]
        if not compatible:
            return [], "no_compatible_device"
        online = [device for device in compatible if device.last_heartbeat and device.last_heartbeat >= cutoff]
        if not online:
            return [], "compatible_devices_offline"
        unreserved = [device for device in online if device.id not in active_device_ids]
        if not unreserved:
            return [], "compatible_devices_busy"
        idle = [device for device in unreserved if device.status in {"idle", "ready"}]
        if not idle:
            return [], "compatible_devices_busy"
        powered = [device for device in idle if device.battery >= settings.low_battery_threshold]
        if not powered:
            return [], "compatible_devices_low_battery"
        return [_device_state(device) for device in powered], "awaiting_candidate"

    async def _device_is_still_available(self, session, task: Task, device: Device) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.gateway_offline_after_seconds)
        if not device.gateway_enabled or not device_is_compatible(task, device):
            return False
        if not device.last_heartbeat or device.last_heartbeat < cutoff:
            return False
        if device.status not in {"idle", "ready"} or device.battery < settings.low_battery_threshold:
            return False
        active_execution_id = await session.scalar(
            select(MissionExecution.id).where(
                MissionExecution.device_id == device.id,
                MissionExecution.state.in_(ACTIVE_EXECUTION_STATES),
            )
        )
        return active_execution_id is None

    def _device_is_compatible(
        self,
        task: Task,
        device: Device,
        *,
        capability_code: str | None = None,
    ) -> bool:
        return device_is_compatible(task, device, capability_code=capability_code)

    @staticmethod
    def _set_dispatch_waiting(task: Task, state: str, reason: str) -> bool:
        changed = task.dispatch_state != state or task.dispatch_reason != reason
        task.dispatch_state = state
        task.dispatch_reason = reason
        return changed

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
        return PROCESS_DEVICE_TYPES.get(process_id)

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
        "connection_status": connection_status(device.last_heartbeat),
    }


def _is_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _task_payload(task: Task) -> dict:
    # Keep REST and WebSocket task shapes identical so PM never has to infer
    # resource-plan fields from partial event payloads.
    from app.api.tasks import _task_dict

    return _task_dict(task)


def _legacy_task_payload(task: Task) -> dict:
    device = task.__dict__.get("device")
    point = task.__dict__.get("map_point")
    return_point = task.__dict__.get("return_point")
    return {
        "id": str(task.id), "code": task.code, "name": task.name, "process_id": task.process_id,
        "device_id": str(task.device_id) if task.device_id else None,
        "device_code": device.code if device else None, "status": task.status, "priority": task.priority,
        "map_point_id": str(task.map_point_id) if task.map_point_id else None,
        "map_point_code": point.code if point else None, "map_point_name": point.name if point else None,
        "return_policy": task.return_policy,
        "return_point_id": str(task.return_point_id) if task.return_point_id else None,
        "return_point_code": return_point.code if return_point else None,
        "return_point_name": return_point.name if return_point else None,
        "work_parameters": task.work_parameters or {},
        "dispatch_state": task.dispatch_state,
        "dispatch_reason": task.dispatch_reason,
        "dispatch_attempts": task.dispatch_attempts,
        "last_dispatch_attempt_at": task.last_dispatch_attempt_at.isoformat() if task.last_dispatch_attempt_at else None,
        "current_phase": task.current_phase,
        "progress": task.progress, "dependencies": task.dependencies or [], "estimated_duration": task.estimated_duration,
        "planned_start": task.planned_start.isoformat() if task.planned_start else None,
        "planned_end": task.planned_end.isoformat() if task.planned_end else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "deliverable_qty": task.deliverable_qty, "deliverable_unit": task.deliverable_unit,
        "completed_qty": task.completed_qty, "stage": task.stage, "params": task.params or {},
    }
