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

from app.models.models import Device, DeviceCommand, DeviceEvent, MissionExecution, Task


def now() -> datetime:
    return datetime.now(timezone.utc)


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
    target: dict[str, float],
) -> MissionExecution:
    """Create a mission and command atomically; execution starts only after gateway telemetry confirms it."""

    execution = MissionExecution(
        task_id=task.id,
        device_id=device.id,
        gateway_execution_id=str(uuid.uuid4()),
        state="dispatched",
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
            "execution_id": execution.gateway_execution_id,
            "task_id": str(task.id),
            "task_code": task.code,
            "process_id": task.process_id,
            "target": target,
            "constraints": task.params.get("constraints", {}),
        },
    )
    task.device_id = device.id
    task.status = "assigned"
    # Reserve the device immediately so another scheduler tick cannot dispatch
    # a second mission while this command is awaiting gateway acceptance.
    device.status = "assigned"
    params = dict(task.params or {})
    params.pop("pending_control", None)
    params.pop("pending_reassignment", None)
    task.params = params
    return execution


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

    task = await db.get(Task, execution.task_id)
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
        "dispatched": {"accepted", "running", "failed", "cancelled"},
        "accepted": {"running", "paused", "failed", "cancelled"},
        "running": {"paused", "completed", "failed", "cancelled"},
        "paused": {"running", "failed", "cancelled"},
        "pause_requested": {"pause_requested", "paused", "completed", "failed", "cancelled"},
        "resume_requested": {"resume_requested", "running", "failed", "cancelled"},
        "cancel_requested": {"cancel_requested", "completed", "failed", "cancelled"},
        "completed": {"completed"},
        "failed": {"failed"},
        "cancelled": {"cancelled"},
    }
    if state not in allowed.get(execution.state, set()):
        raise HTTPException(status_code=409, detail=f"invalid execution transition {execution.state} -> {state}")

    timestamp = now()
    execution.state = state
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
        if state in {"accepted", "running", "paused"}:
            task.status = "running" if state == "running" else ("assigned" if state == "accepted" else "paused")
            task.started_at = task.started_at or timestamp
        elif state == "completed":
            task.status = "completed"
            task.progress = 100.0
            task.completed_qty = completed_qty if completed_qty is not None else task.deliverable_qty or task.completed_qty
            task.completed_at = timestamp
        elif state in {"failed", "cancelled"}:
            if state == "failed":
                task.status = "failed"
            elif (task.params or {}).get("pending_reassignment"):
                # The scheduler consumes this durable intent and only dispatches
                # to the originally selected target after cancellation is real.
                task.status = "reassign_pending"
            else:
                task.status = "pending"
            if state == "cancelled":
                task.device_id = None
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
        else:
            metrics.pop("current_task", None)
            metrics.pop("task_progress", None)
        device.operational_metrics = metrics
    return execution
