"""Durable gateway command and mission lifecycle service.

The service is protocol-neutral: physical robots and Gazebo bridges consume the
same HTTP gateway contract. It intentionally contains no ROS client code.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    Device,
    DeviceCommand,
    DeviceEvent,
    MapPoint,
    MissionExecution,
    Project,
    Task,
    TaskResourceAllocation,
    TaskResourcePlan,
    TaskResourceRequirement,
)


MISSION_PHASE_SEQUENCE = (
    "preparing",
    "navigating_to_target",
    "arrived_at_target",
    "working",
    "work_completed",
    "returning",
    "returned",
)
MISSION_PHASES = set(MISSION_PHASE_SEQUENCE)
MISSION_PHASE_ORDER = {phase: index for index, phase in enumerate(MISSION_PHASE_SEQUENCE)}
ACTIVE_EXECUTION_STATES = {
    "dispatched",
    "accepted",
    "running",
    "paused",
    "pause_requested",
    "resume_requested",
    "cancel_requested",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


async def build_mission_navigation(
    db: AsyncSession,
    task: Task,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve persisted task points into one explicit map-frame navigation plan."""

    projects = (
        await db.execute(select(Project).where(Project.is_active.is_(True)).order_by(Project.created_at.desc()).limit(2))
    ).scalars().all()
    if len(projects) != 1:
        raise HTTPException(status_code=409, detail="任务派发要求数据库中存在唯一活动项目。")
    project = projects[0]
    target_point = await db.get(MapPoint, task.map_point_id) if task.map_point_id else None
    if target_point is None:
        raise HTTPException(status_code=409, detail="任务目标点位不存在，无法派发。")

    def point_payload(point: MapPoint) -> dict[str, Any]:
        return {
            "point_id": str(point.id),
            "point_code": point.code,
            "frame_id": project.map_frame,
            "x": point.x,
            "y": point.y,
            "z": point.z,
        }

    target = point_payload(target_point)
    return_policy = getattr(task, "return_policy", "stay") or "stay"
    if return_policy == "stay":
        return target, {"policy": "stay", "target": None}
    if return_policy != "return_to_point" or not getattr(task, "return_point_id", None):
        raise HTTPException(status_code=409, detail="任务返航策略缺少有效的返回点位。")
    return_point = await db.get(MapPoint, task.return_point_id)
    if return_point is None:
        raise HTTPException(status_code=409, detail="任务返回点位不存在，无法派发。")
    return target, {"policy": "return_to_point", "target": point_payload(return_point)}


async def queue_command(
    db: AsyncSession,
    device: Device,
    command: str,
    *,
    payload: dict[str, Any] | None = None,
    source: str = "system",
    priority: int = 50,
    idempotency_key: str | None = None,
    mission_execution_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> DeviceCommand:
    """Queue one idempotent command and write its immutable audit event."""

    key = idempotency_key or f"{source}:{device.id}:{command}:{uuid.uuid4()}"
    existing = await db.scalar(select(DeviceCommand).where(DeviceCommand.idempotency_key == key))
    if existing:
        return existing

    queued = DeviceCommand(
        device_id=device.id,
        command=command,
        payload=payload or {},
        idempotency_key=key,
        source=source,
        priority=priority,
        mission_execution_id=mission_execution_id,
        expires_at=expires_at,
    )
    db.add(queued)
    await db.flush()
    db.add(
        DeviceEvent(
            time=now(),
            device_id=device.id,
            event_type="command_queued",
            payload={"command_id": str(queued.id), "command": command, "payload": queued.payload, "source": source},
        )
    )
    return queued


async def dispatch_mission(
    db: AsyncSession,
    task: Task,
    device: Device,
    target: dict[str, Any],
    return_plan: dict[str, Any] | None = None,
    allocation: TaskResourceAllocation | None = None,
) -> MissionExecution:
    """Create a mission and command atomically; execution starts only after gateway telemetry confirms it."""

    protocol_version = "v2" if getattr(device, "protocol_version", "v1") == "v2" else "v1"
    requires_v2 = (
        getattr(task, "return_policy", "stay") == "return_to_point"
        or bool(getattr(task, "work_parameters", {}) or {})
    )
    if requires_v2 and protocol_version != "v2":
        raise HTTPException(status_code=409, detail="该任务需要支持 v2 作业编排协议的机器人设备。")
    return_payload = return_plan or {"policy": "stay", "target": None}
    assigned_qty = allocation.planned_qty if allocation is not None else task.deliverable_qty
    output_unit = allocation.output_unit if allocation is not None else task.deliverable_unit
    work_payload = {
        "process_id": task.process_id,
        "parameters": getattr(task, "work_parameters", {}) or {},
        "instructions": (task.params or {}).get("description"),
        "deliverable_qty": assigned_qty,
        "deliverable_unit": output_unit,
        "task_total_qty": task.deliverable_qty,
        "task_total_unit": task.deliverable_unit,
    }
    execution = MissionExecution(
        task_id=task.id,
        device_id=device.id,
        allocation_id=allocation.id if allocation is not None else None,
        gateway_execution_id=str(uuid.uuid4()),
        protocol_version=protocol_version,
        state="dispatched",
        phase="preparing",
        phase_sequence=0,
        phase_progress=0.0,
        phase_updated_at=now(),
        planned_qty=assigned_qty,
        output_unit=output_unit,
        rate_per_hour_snapshot=allocation.rate_per_hour_snapshot if allocation is not None else None,
    )
    db.add(execution)
    await db.flush()
    await queue_command(
        db,
        device,
        "mission_start",
        source="scheduler",
        priority=task.priority,
        mission_execution_id=execution.id,
        idempotency_key=f"mission_start:{execution.id}",
        payload={
            "schema_version": protocol_version,
            "execution_id": execution.gateway_execution_id,
            "task_id": str(task.id),
            "task_code": task.code,
            "process_id": task.process_id,
            "target": target,
            "map_frame": target.get("frame_id"),
            "workflow": {
                "outbound": {"target": target},
                "operation": work_payload,
                "return": {
                    "required": return_payload.get("policy") == "return_to_point",
                    **return_payload,
                },
            },
            "work": work_payload,
            "allocation": {
                "allocation_id": str(allocation.id),
                "requirement_id": str(allocation.requirement_id),
                "role_code": allocation.requirement.role_code if allocation.requirement else None,
                "assigned_qty": allocation.planned_qty,
                "output_unit": allocation.output_unit,
                "work_scope": allocation.work_scope or {},
                "predicted_finish_at": allocation.predicted_finish_at.isoformat() if allocation.predicted_finish_at else None,
            } if allocation is not None else None,
            "constraints": (task.params or {}).get("constraints", {}),
            "return": return_payload,
            "completion_policy": "after_return"
            if return_payload.get("policy") == "return_to_point"
            else "after_work",
        },
    )
    if allocation is not None:
        allocation.state = "dispatched"
    task.device_id = task.device_id or device.id
    task.status = "assigned"
    task.dispatch_state = "dispatched"
    task.dispatch_reason = None
    task.current_phase = "preparing"
    # Reserve the device immediately so another scheduler tick cannot dispatch
    # a second mission while this command is awaiting gateway acceptance.
    device.status = "assigned"
    params = dict(task.params or {})
    params.pop("pending_control", None)
    params.pop("pending_reassignment", None)
    task.params = params
    return execution


async def _aggregate_allocated_task(
    db: AsyncSession,
    task: Task,
    timestamp: datetime,
) -> bool:
    """Aggregate per-device telemetry; no individual unit may complete the parent alone."""

    requirements = (
        await db.execute(
            select(TaskResourceRequirement).where(TaskResourceRequirement.task_id == task.id)
        )
    ).scalars().all()
    if not requirements:
        return False
    allocations = (
        await db.execute(
            select(TaskResourceAllocation).where(TaskResourceAllocation.task_id == task.id)
        )
    ).scalars().all()
    by_requirement: dict[uuid.UUID, list[TaskResourceAllocation]] = {}
    for allocation in allocations:
        by_requirement.setdefault(allocation.requirement_id, []).append(allocation)
    gate_ratios: list[float] = []
    primary_completed: float | None = None
    for requirement in requirements:
        completed = sum(item.completed_qty for item in by_requirement.get(requirement.id, []))
        requirement.completed_qty = min(requirement.required_qty, completed)
        if requirement.role_code == "primary" and requirement.output_unit == task.deliverable_unit:
            primary_completed = requirement.completed_qty
        if requirement.is_completion_gate:
            gate_ratios.append(min(1.0, requirement.completed_qty / requirement.required_qty))
    if primary_completed is not None:
        task.completed_qty = primary_completed
    task.progress = min(gate_ratios, default=0.0) * 100.0
    all_gates_satisfied = bool(gate_ratios) and all(ratio >= 1.0 for ratio in gate_ratios)
    active_allocations = [
        allocation for allocation in allocations
        if allocation.state in {
            "planned", "dispatched", "accepted", "running", "paused",
            "pause_requested", "resume_requested", "cancel_requested",
        }
    ]
    plan = await db.scalar(select(TaskResourcePlan).where(TaskResourcePlan.task_id == task.id))
    # Gateways may retransmit terminal telemetry. A previously confirmed
    # cancellation is immutable and must never re-enter planning.
    if task.status == "cancelled" or getattr(task, "cancelled_at", None) is not None:
        await _finalize_task_cancellation(db, task, timestamp, plan)
        return False
    if task.status == "cancel_requested":
        if not active_allocations:
            await _finalize_task_cancellation(db, task, timestamp, plan)
        return False
    if all_gates_satisfied and not active_allocations:
        task.status = "completed"
        task.dispatch_state = "finished"
        task.dispatch_reason = None
        task.progress = 100.0
        task.completed_at = timestamp
        task.current_phase = "work_completed"
        if plan is not None:
            plan.state = "completed"
            plan.reason = None
        return True
    if active_allocations:
        if all(item.state == "paused" for item in active_allocations):
            task.status = "paused"
        else:
            task.status = "running" if any(item.state == "running" for item in active_allocations) else "assigned"
        task.dispatch_state = "dispatched"
        task.dispatch_reason = None
        if plan is not None:
            plan.state = "executing"
            plan.reason = None
    else:
        task.status = "pending"
        task.dispatch_state = "waiting_capacity"
        task.dispatch_reason = "allocation_replanning"
        if plan is not None:
            plan.state = "waiting_capacity"
            plan.reason = "allocation_replanning"
    return False


async def _finalize_task_cancellation(
    db: AsyncSession,
    task: Task,
    timestamp: datetime,
    plan: TaskResourcePlan | None = None,
) -> None:
    """Finish an operator cancellation only after all units are terminal."""

    task.status = "cancelled"
    task.dispatch_state = "cancelled"
    task.dispatch_reason = "operator_cancelled"
    task.cancelled_at = timestamp
    task.device_id = None
    if plan is None:
        plan = await db.scalar(select(TaskResourcePlan).where(TaskResourcePlan.task_id == task.id))
    if plan is not None:
        plan.state = "cancelled"
        plan.reason = "operator_cancelled"


async def apply_execution_telemetry(
    db: AsyncSession,
    device: Device,
    *,
    execution_id: str | None,
    execution_state: str | None,
    progress: float | None,
    completed_qty: float | None,
    result: dict[str, Any] | None,
    failure_code: str | None,
    estimated_completion_at: datetime | None = None,
    phase: str | None = None,
    phase_sequence: int | None = None,
    phase_progress: float | None = None,
) -> MissionExecution | None:
    """Project validated gateway execution telemetry to mission and task records."""

    if not execution_id:
        return None
    execution = await db.scalar(
        select(MissionExecution).where(
            MissionExecution.gateway_execution_id == execution_id,
            MissionExecution.device_id == device.id,
        )
    )
    if execution is None:
        raise HTTPException(status_code=409, detail="unknown execution_id for device")

    # Serialize telemetry projection with task cancellation and scheduler
    # dispatch so a stale report cannot overwrite a newer control decision.
    task = await db.scalar(
        select(Task).where(Task.id == execution.task_id).with_for_update()
    )
    execution_result = dict(getattr(execution, "result", {}) or {})
    reported_state = execution_state or execution.state
    control_return_state = str(execution_result.get("control_return_state") or "")
    control_request = execution.state

    # A bridge can continue reporting its current state while a pause, resume,
    # or cancel command is in flight. Keep the requested state until telemetry
    # confirms the requested transition; otherwise a routine status report could
    # accidentally erase an operator's pending control request.
    if (
        control_request in {"pause_requested", "resume_requested", "cancel_requested"}
        and reported_state == control_return_state
    ):
        state = control_request
    else:
        state = reported_state
    allowed = {
        "dispatched": {"dispatched", "accepted", "running", "failed", "cancelled"},
        "accepted": {"accepted", "running", "paused", "failed", "cancelled"},
        "running": {"running", "paused", "completed", "failed", "cancelled"},
        "paused": {"paused", "running", "failed", "cancelled"},
        "pause_requested": {"pause_requested", "paused", "completed", "failed", "cancelled"},
        "resume_requested": {"resume_requested", "running", "failed", "cancelled"},
        "cancel_requested": {"cancel_requested", "completed", "failed", "cancelled"},
        "completed": {"completed"},
        "failed": {"failed"},
        "cancelled": {"cancelled"},
    }
    if state not in allowed.get(execution.state, set()):
        raise HTTPException(status_code=409, detail=f"invalid execution transition {execution.state} -> {state}")
    if phase is not None and phase not in MISSION_PHASES:
        raise HTTPException(status_code=422, detail=f"unsupported mission phase: {phase}")
    protocol_version = getattr(execution, "protocol_version", "v1")
    if protocol_version == "v2" and state not in {"failed", "cancelled"}:
        if phase is None or phase_sequence is None or phase_progress is None:
            raise HTTPException(status_code=422, detail="v2 任务遥测必须提供 phase、phase_sequence 和 phase_progress。")
        current_sequence = getattr(execution, "phase_sequence", 0)
        current_phase = getattr(execution, "phase", "preparing")
        current_progress = getattr(execution, "phase_progress", 0.0)
        if phase_sequence < current_sequence:
            raise HTTPException(status_code=409, detail="任务阶段序号不能回退。")
        if phase_sequence == current_sequence:
            if phase != current_phase or phase_progress != current_progress:
                raise HTTPException(status_code=409, detail="相同任务阶段序号不能携带不同内容。")
        else:
            if phase_sequence != current_sequence + 1:
                raise HTTPException(status_code=409, detail="任务阶段序号必须连续递增。")
            current_rank = MISSION_PHASE_ORDER[current_phase]
            next_rank = MISSION_PHASE_ORDER[phase]
            if next_rank < current_rank or next_rank > current_rank + 1:
                raise HTTPException(status_code=409, detail="任务执行阶段不能回退或跳过关键阶段。")
            if phase == current_phase and phase_progress < current_progress:
                raise HTTPException(status_code=409, detail="同一任务阶段的进度不能回退。")
    if state == "completed" and protocol_version == "v2" and task:
        requires_return = getattr(task, "return_policy", "stay") == "return_to_point"
        required_phase = "returned" if requires_return else "work_completed"
        if phase != required_phase:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "mission_phase_incomplete",
                    "message": "机器人尚未完成任务要求的作业或返航阶段，不能结束任务。",
                    "required_phase": required_phase,
                },
            )
    if state == "completed" and task and getattr(task, "return_policy", "stay") == "return_to_point":
        reported_result = result or {}
        expected_return_point_id = str(getattr(task, "return_point_id", ""))
        if (
            phase != "returned"
            or reported_result.get("return_completed") is not True
            or str(reported_result.get("return_point_id") or "") != expected_return_point_id
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "return_not_confirmed",
                    "message": "任务要求作业后返回指定点位，设备确认返航完成前不能结束任务。",
                    "return_point_id": expected_return_point_id,
                },
            )

    timestamp = now()
    execution.state = state
    if phase is not None:
        execution.phase = phase
        execution.phase_sequence = phase_sequence if phase_sequence is not None else execution.phase_sequence
        execution.phase_progress = phase_progress if phase_progress is not None else execution.phase_progress
        execution.phase_updated_at = timestamp
    execution.result = {**execution_result, **(result or {})}
    if estimated_completion_at is not None:
        execution.result["estimated_completion_at"] = estimated_completion_at.isoformat()
    execution.failure_code = failure_code
    if progress is not None:
        execution.progress = progress
    if completed_qty is not None:
        execution.completed_qty = completed_qty
    if state == "accepted" and execution.accepted_at is None:
        execution.accepted_at = timestamp
    if state == "running" and execution.started_at is None:
        execution.started_at = timestamp
    if state in {"completed", "failed", "cancelled"}:
        execution.completed_at = timestamp

    if task:
        allocation = None
        if getattr(execution, "allocation_id", None) is not None:
            allocation = await db.get(TaskResourceAllocation, execution.allocation_id)
        if allocation is not None:
            allocation.state = state
            if completed_qty is not None:
                allocation.completed_qty = min(allocation.planned_qty, completed_qty)
            if state == "running":
                task.started_at = task.started_at or timestamp
            if phase is not None:
                task.current_phase = phase
            elif state == "completed":
                task.current_phase = "returned" if getattr(task, "return_policy", "stay") == "return_to_point" else "work_completed"
            await db.flush()
            await _aggregate_allocated_task(db, task, timestamp)
            params = dict(getattr(task, "params", {}) or {})
            pending_control = params.get("pending_control")
            if (
                pending_control
                and pending_control.get("execution_id") == execution.gateway_execution_id
                and state in {"paused", "running", "completed", "failed", "cancelled"}
            ):
                params.pop("pending_control", None)
            task.params = params
            metrics = dict(getattr(device, "operational_metrics", {}) or {})
            if state in {"accepted", "running", "paused"}:
                metrics["current_task"] = getattr(task, "code", str(task.id))
                metrics["task_progress"] = task.progress
                metrics["mission_phase"] = getattr(execution, "phase", None)
            else:
                metrics.pop("current_task", None)
                metrics.pop("task_progress", None)
                metrics.pop("mission_phase", None)
            device.operational_metrics = metrics
            if state == "accepted":
                device.status = "assigned"
            elif state == "running":
                device.status = "working"
            elif state == "paused":
                device.status = "paused"
            return execution
        if task.status == "cancel_requested" and state in {"completed", "failed", "cancelled"}:
            other_active_execution = await db.scalar(
                select(MissionExecution.id).where(
                    MissionExecution.task_id == task.id,
                    MissionExecution.id != execution.id,
                    MissionExecution.state.in_(ACTIVE_EXECUTION_STATES),
                ).limit(1)
            )
            if other_active_execution is None:
                await _finalize_task_cancellation(db, task, timestamp)
        elif state in {"accepted", "running", "paused"}:
            task.status = "running" if state == "running" else ("assigned" if state == "accepted" else "paused")
            task.dispatch_state = "dispatched"
            task.dispatch_reason = None
            if state == "running":
                task.started_at = task.started_at or timestamp
        elif state == "completed":
            task.status = "completed"
            task.dispatch_state = "finished"
            task.dispatch_reason = None
            task.progress = 100.0
            task.completed_qty = completed_qty if completed_qty is not None else task.deliverable_qty or task.completed_qty
            task.completed_at = timestamp
        elif state in {"failed", "cancelled"}:
            if state == "failed":
                task.status = "failed"
                task.dispatch_state = "failed"
                task.dispatch_reason = failure_code or "device_reported_failure"
            elif (task.params or {}).get("pending_reassignment"):
                # The scheduler consumes this durable intent and only dispatches
                # to the originally selected target after cancellation is real.
                task.status = "reassign_pending"
                task.dispatch_state = "waiting_device"
                task.dispatch_reason = "waiting_reassignment_target"
            else:
                task.status = "pending"
                task.dispatch_state = "waiting_device"
                task.dispatch_reason = "mission_cancelled"
            if state == "cancelled":
                task.device_id = None
        if phase is not None:
            task.current_phase = phase
        elif state == "completed":
            task.current_phase = "returned" if getattr(task, "return_policy", "stay") == "return_to_point" else "work_completed"
        if progress is not None and state != "completed":
            task.progress = progress
        if completed_qty is not None and state != "completed":
            task.completed_qty = completed_qty
        params = dict(getattr(task, "params", {}) or {})
        pending_control = params.get("pending_control")
        if (
            pending_control
            and pending_control.get("execution_id") == execution.gateway_execution_id
            and state in {"paused", "running", "completed", "failed", "cancelled"}
        ):
            params.pop("pending_control", None)
        task.params = params
        metrics = dict(getattr(device, "operational_metrics", {}) or {})
        if state in {"accepted", "running", "paused"}:
            metrics["current_task"] = getattr(task, "code", str(task.id))
            metrics["task_progress"] = task.progress
            metrics["mission_phase"] = getattr(execution, "phase", None)
        else:
            metrics.pop("current_task", None)
            metrics.pop("task_progress", None)
            metrics.pop("mission_phase", None)
        device.operational_metrics = metrics
        if state == "accepted":
            device.status = "assigned"
        elif state == "running":
            device.status = "working"
        elif state == "paused":
            device.status = "paused"
    return execution
