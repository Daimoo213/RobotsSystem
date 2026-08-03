"""Capacity-driven resource planning for multi-device construction tasks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.models import (
    Device,
    DeviceWorkCapacity,
    MissionExecution,
    Task,
    TaskResourceAllocation,
    TaskResourcePlan,
    TaskResourceRequirement,
)
from app.scheduler.matching import capability_codes_match, device_is_compatible


ACTIVE_ALLOCATION_STATES = {
    "planned", "dispatched", "accepted", "running", "paused", "pause_requested", "resume_requested", "cancel_requested",
}
ACTIVE_EXECUTION_STATES = {
    "dispatched", "accepted", "running", "paused", "pause_requested", "resume_requested", "cancel_requested",
}


@dataclass(frozen=True)
class AllocationProposal:
    requirement: TaskResourceRequirement
    device: Device
    capacity: DeviceWorkCapacity
    planned_qty: float
    available_from: datetime
    predicted_finish_at: datetime


@dataclass(frozen=True)
class ResourcePlanDecision:
    plan: TaskResourcePlan
    state: str
    reason: str | None
    proposals: tuple[AllocationProposal, ...]
    is_sufficient: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _unit_matches(left: str, right: str) -> bool:
    return left.strip() == right.strip()


def _effective_window(task: Task, at: datetime) -> tuple[datetime, datetime] | None:
    if task.planned_start is None or task.planned_end is None:
        return None
    start = max(task.planned_start, at)
    if task.planned_end <= start:
        return None
    return start, task.planned_end


def _capacity_bid(device: Device, rate_per_hour: float, target: tuple[float, float]) -> float:
    """Rank equal-capacity devices without pretending to know their actual output."""

    distance = math.hypot(device.position_x - target[0], device.position_y - target[1])
    return (distance * 0.5 + (100.0 - device.battery) * 0.3) / rate_per_hour


async def _get_plan(db: AsyncSession, task: Task) -> TaskResourcePlan:
    plan = await db.scalar(select(TaskResourcePlan).where(TaskResourcePlan.task_id == task.id))
    if plan is None:
        plan = TaskResourcePlan(task_id=task.id, task=task)
        db.add(plan)
        await db.flush()
    return plan


async def ensure_default_requirement(db: AsyncSession, task: Task) -> list[TaskResourceRequirement]:
    """Create only the direct, user-selected process requirement when input is complete."""

    requirements = (
        await db.execute(
            select(TaskResourceRequirement).where(TaskResourceRequirement.task_id == task.id)
        )
    ).scalars().all()
    if requirements or not task.deliverable_qty or not task.deliverable_unit:
        return requirements
    requirement = TaskResourceRequirement(
        task_id=task.id,
        task=task,
        role_code="primary",
        capability_code=task.process_id,
        required_qty=task.deliverable_qty,
        output_unit=task.deliverable_unit,
        work_scope={"mode": "shared_queue", "map_point_id": str(task.map_point_id)},
    )
    db.add(requirement)
    await db.flush()
    return [requirement]


async def plan_task_resources(
    db: AsyncSession,
    task: Task,
    *,
    at: datetime | None = None,
) -> ResourcePlanDecision:
    """Calculate a real, non-binding resource plan from registered capacity data."""

    planning_at = at or _now()
    plan = await _get_plan(db, task)
    requirements = await ensure_default_requirement(db, task)
    if not requirements:
        plan.state = "waiting_planning_input"
        plan.reason = "planning_input_required"
        plan.window_start = task.planned_start
        plan.window_end = task.planned_end
        plan.required_rate_per_hour = None
        plan.planned_rate_per_hour = 0.0
        plan.coverage_ratio = 0.0
        plan.predicted_completion_at = None
        plan.summary = {"requirements": [], "message": "缺少真实交付量、单位或资源需求，不能计算设备数量。"}
        return ResourcePlanDecision(plan, plan.state, plan.reason, (), False)

    window = _effective_window(task, planning_at)
    if window is None:
        plan.state = "waiting_planning_input" if task.planned_start is None or task.planned_end is None else "at_risk"
        plan.reason = "planning_window_required" if plan.state == "waiting_planning_input" else "planned_end_passed"
        plan.window_start = task.planned_start
        plan.window_end = task.planned_end
        plan.required_rate_per_hour = None
        plan.planned_rate_per_hour = 0.0
        plan.coverage_ratio = 0.0
        plan.predicted_completion_at = None
        plan.summary = {"requirements": [], "message": "必须提供尚未结束的计划开始和结束时间。"}
        return ResourcePlanDecision(plan, plan.state, plan.reason, (), False)

    window_start, window_end = window
    available_hours = (window_end - window_start).total_seconds() / 3600.0
    if available_hours <= 0:
        plan.state = "at_risk"
        plan.reason = "no_available_working_time"
        return ResourcePlanDecision(plan, plan.state, plan.reason, (), False)

    requirements = (
        await db.execute(
            select(TaskResourceRequirement)
            .where(TaskResourceRequirement.task_id == task.id)
            .options(selectinload(TaskResourceRequirement.allocations))
        )
    ).scalars().all()
    allocations = (
        await db.execute(
            select(TaskResourceAllocation).where(TaskResourceAllocation.task_id == task.id)
        )
    ).scalars().all()
    active_allocations = [allocation for allocation in allocations if allocation.state in ACTIVE_ALLOCATION_STATES]

    task_devices = await db.execute(
        select(Device).options(selectinload(Device.work_capacities)).where(Device.gateway_enabled.is_(True))
    )
    devices = task_devices.scalars().all()
    active_device_ids = set(
        (
            await db.execute(
                select(MissionExecution.device_id).where(MissionExecution.state.in_(ACTIVE_EXECUTION_STATES))
            )
        ).scalars().all()
    )
    # Devices already executing the same task keep their existing allocation;
    # their reserved remaining quota is counted below rather than dispatched again.
    own_active_device_ids = {allocation.device_id for allocation in active_allocations}
    active_device_ids.difference_update(own_active_device_ids)
    cutoff = planning_at - timedelta(seconds=settings.gateway_offline_after_seconds)
    target = (task.map_point.x, task.map_point.y) if task.map_point is not None else (0.0, 0.0)

    proposals: list[AllocationProposal] = []
    requirement_summaries: list[dict] = []
    selected_device_ids: set = set(active_device_ids)
    coverage_values: list[float] = []
    required_rate_total = 0.0
    planned_rate_total = 0.0
    predicted_finish: datetime | None = None
    insufficient_reason: str | None = None

    for requirement in requirements:
        completed = max(0.0, requirement.completed_qty)
        reserved = sum(
            max(0.0, allocation.planned_qty - allocation.completed_qty)
            for allocation in active_allocations
            if allocation.requirement_id == requirement.id
        )
        remaining = max(0.0, requirement.required_qty - completed - reserved)
        required_rate = max(0.0, requirement.required_qty - completed) / available_hours
        required_rate_total += required_rate

        candidate_rows: list[tuple[Device, DeviceWorkCapacity, float, float]] = []
        for device in devices:
            if device.id in selected_device_ids or device.id in own_active_device_ids:
                continue
            if not device.last_heartbeat or device.last_heartbeat < cutoff:
                continue
            if device.status not in {"idle", "ready"} or device.battery < settings.low_battery_threshold:
                continue
            if not device_is_compatible(task, device, capability_code=requirement.capability_code):
                continue
            matching_capacities = [
                capacity
                for capacity in device.work_capacities
                if _unit_matches(capacity.output_unit, requirement.output_unit)
                and capacity.rate_per_hour > 0
                and (capacity.valid_until is None or capacity.valid_until >= planning_at)
                and capability_codes_match(requirement.capability_code, capacity.capability_code)
            ]
            if not matching_capacities:
                continue
            capacity = max(matching_capacities, key=lambda item: item.rate_per_hour)
            deliverable = capacity.rate_per_hour * available_hours
            candidate_rows.append((device, capacity, deliverable, _capacity_bid(device, capacity.rate_per_hour, target)))

        candidate_rows.sort(key=lambda item: (-item[2], item[3], item[0].code))
        selected_for_requirement: list[AllocationProposal] = []
        required_remaining = remaining
        for device, capacity, deliverable, _bid in candidate_rows:
            if required_remaining <= 1e-9:
                break
            planned_qty = min(required_remaining, deliverable)
            finish = window_start + timedelta(hours=planned_qty / capacity.rate_per_hour)
            proposal = AllocationProposal(
                requirement=requirement,
                device=device,
                capacity=capacity,
                planned_qty=planned_qty,
                available_from=window_start,
                predicted_finish_at=finish,
            )
            proposals.append(proposal)
            selected_for_requirement.append(proposal)
            selected_device_ids.add(device.id)
            required_remaining -= planned_qty
            planned_rate_total += capacity.rate_per_hour
            if predicted_finish is None or finish > predicted_finish:
                predicted_finish = finish

        covered = requirement.required_qty - max(0.0, required_remaining)
        coverage = min(1.0, (completed + reserved + sum(item.planned_qty for item in selected_for_requirement)) / requirement.required_qty)
        coverage_values.append(coverage)
        if required_remaining > 1e-9 and insufficient_reason is None:
            insufficient_reason = "insufficient_capacity" if candidate_rows else "no_valid_capacity_device"
        planned_types: dict[str, dict] = {}
        for proposal in selected_for_requirement:
            item = planned_types.setdefault(
                proposal.device.type,
                {
                    "device_type": proposal.device.type,
                    "planned_count": 0,
                    "available_count": 0,
                    "planned_qty": 0.0,
                    "planned_rate_per_hour": 0.0,
                },
            )
            item["planned_count"] += 1
            item["planned_qty"] += proposal.planned_qty
            item["planned_rate_per_hour"] += proposal.capacity.rate_per_hour
        for device, _capacity, _deliverable, _bid in candidate_rows:
            summary = planned_types.setdefault(
                device.type,
                {
                    "device_type": device.type,
                    "planned_count": 0,
                    "available_count": 0,
                    "planned_qty": 0.0,
                    "planned_rate_per_hour": 0.0,
                },
            )
            summary["available_count"] += 1
        requirement_summaries.append(
            {
                "requirement_id": str(requirement.id),
                "role_code": requirement.role_code,
                "capability_code": requirement.capability_code,
                "required_qty": requirement.required_qty,
                "completed_qty": completed,
                "reserved_qty": reserved,
                "planned_qty": sum(item.planned_qty for item in selected_for_requirement),
                "remaining_qty": max(0.0, required_remaining),
                "output_unit": requirement.output_unit,
                "required_rate_per_hour": required_rate,
                "coverage_ratio": coverage,
                "device_types": list(planned_types.values()),
            }
        )

    is_sufficient = all(value >= 1.0 for value in coverage_values)
    if is_sufficient:
        state = "preplanned" if task.planned_start and task.planned_start > planning_at else "ready_to_dispatch"
        reason = None
        if active_allocations and not proposals:
            state = "executing"
    else:
        state = "waiting_capacity"
        reason = insufficient_reason or "insufficient_capacity"
    plan.state = state
    plan.reason = reason
    plan.window_start = window_start
    plan.window_end = window_end
    plan.required_rate_per_hour = required_rate_total
    plan.planned_rate_per_hour = planned_rate_total
    plan.coverage_ratio = min(coverage_values, default=0.0)
    plan.predicted_completion_at = predicted_finish
    plan.summary = {
        "requirements": requirement_summaries,
        "selection_is_live": task.planned_start is None or task.planned_start <= planning_at,
        "candidate_basis": "仅统计当前在线、空闲、可用电量且存在有效真实产能声明的设备。",
    }
    return ResourcePlanDecision(plan, state, reason, tuple(proposals), is_sufficient)
