from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.models import MissionExecution, TaskResourceAllocation, TaskResourcePlan, TaskResourceRequirement
from app.services.fleet_commands import apply_execution_telemetry


class FakeSession:
    def __init__(self, execution, task):
        self.execution = execution
        self.task = task

    async def scalar(self, _statement):
        return self.execution

    async def get(self, model, _identifier):
        return self.task if model.__name__ == "Task" else None


class CancellationSession:
    """Minimal persistence double for a terminal cancellation confirmation."""

    def __init__(self, execution, task):
        self.execution = execution
        self.task = task
        self._scalar_calls = 0

    async def scalar(self, _statement):
        self._scalar_calls += 1
        # Lookup execution, lookup other active executions, lookup resource plan.
        return self.execution if self._scalar_calls == 1 else None

    async def get(self, model, _identifier):
        return self.task if model.__name__ == "Task" else None


class AllocationSession:
    """Minimal persistence double for verifying task-level allocation aggregation."""

    def __init__(self, task, requirements, allocations, plan):
        self.task = task
        self.requirements = requirements
        self.allocations = allocations
        self.plan = plan
        self.execution = None

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is TaskResourcePlan:
            return self.plan
        return self.execution

    async def get(self, model, identifier):
        if model.__name__ == "Task":
            return self.task
        if model is TaskResourceAllocation:
            return next(item for item in self.allocations if item.id == identifier)
        return None

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is TaskResourceRequirement:
            values = self.requirements
        elif entity is TaskResourceAllocation:
            values = self.allocations
        else:
            values = []
        return type(
            "Result",
            (),
            {"scalars": lambda _self: type("Scalars", (), {"all": lambda _inner: values})()},
        )()

    async def flush(self):
        return None


def _device() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), status="working", operational_metrics={})


def _task(
    device_id: uuid.UUID,
    *,
    return_policy: str = "stay",
    return_point_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status="assigned",
        progress=0.0,
        completed_qty=0.0,
        deliverable_qty=10.0,
        deliverable_unit="t",
        started_at=None,
        completed_at=None,
        device_id=device_id,
        params={},
        dispatch_state="dispatched",
        dispatch_reason=None,
        current_phase="preparing",
        return_policy=return_policy,
        return_point_id=return_point_id,
    )


def _execution(
    task: SimpleNamespace,
    device: SimpleNamespace,
    *,
    protocol_version: str = "v1",
    state: str = "dispatched",
    phase: str = "preparing",
    phase_sequence: int = 0,
    phase_progress: float = 0.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        task_id=task.id,
        device_id=device.id,
        gateway_execution_id=f"exec-{uuid.uuid4()}",
        protocol_version=protocol_version,
        state=state,
        phase=phase,
        phase_sequence=phase_sequence,
        phase_progress=phase_progress,
        phase_updated_at=None,
        progress=0.0,
        result={},
        failure_code=None,
        accepted_at=None,
        started_at=None,
        completed_at=None,
        completed_qty=None,
    )


@pytest.mark.asyncio
async def test_execution_telemetry_projects_task_progress() -> None:
    device = SimpleNamespace(id=uuid.uuid4())
    task = SimpleNamespace(id=uuid.uuid4(), status="assigned", progress=0.0, completed_qty=0.0, deliverable_qty=10.0, started_at=None, completed_at=None, device_id=device.id)
    execution = SimpleNamespace(
        id=uuid.uuid4(), task_id=task.id, device_id=device.id, gateway_execution_id="exec-001",
        state="dispatched", progress=0.0, result={}, failure_code=None,
        accepted_at=None, started_at=None, completed_at=None, completed_qty=None,
    )
    session = FakeSession(execution, task)

    result = await apply_execution_telemetry(
        session, device, execution_id="exec-001", execution_state="running", progress=25.0,
        completed_qty=2.5, result=None, failure_code=None,
    )

    assert result is execution
    assert execution.state == "running"
    assert task.status == "running"
    assert task.progress == 25.0
    assert task.completed_qty == 2.5


@pytest.mark.asyncio
async def test_execution_rejects_invalid_terminal_transition() -> None:
    device = SimpleNamespace(id=uuid.uuid4())
    execution = SimpleNamespace(task_id=uuid.uuid4(), device_id=device.id, gateway_execution_id="exec-002", state="completed")
    session = FakeSession(execution, None)

    with pytest.raises(HTTPException) as error:
        await apply_execution_telemetry(
            session, device, execution_id="exec-002", execution_state="running", progress=10.0,
            completed_qty=None, result=None, failure_code=None,
        )
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_pause_request_waits_for_gateway_pause_confirmation() -> None:
    device = SimpleNamespace(id=uuid.uuid4())
    task = SimpleNamespace(
        id=uuid.uuid4(), status="running", progress=40.0, completed_qty=4.0,
        deliverable_qty=10.0, started_at=None, completed_at=None, device_id=device.id,
        params={"pending_control": {"action": "pause", "execution_id": "exec-003"}},
    )
    execution = SimpleNamespace(
        id=uuid.uuid4(), task_id=task.id, device_id=device.id, gateway_execution_id="exec-003",
        state="pause_requested", progress=40.0,
        result={"control_return_state": "running"}, failure_code=None,
        accepted_at=None, started_at=None, completed_at=None, completed_qty=None,
    )
    session = FakeSession(execution, task)

    await apply_execution_telemetry(
        session, device, execution_id="exec-003", execution_state="running", progress=41.0,
        completed_qty=None, result=None, failure_code=None,
    )

    assert execution.state == "pause_requested"
    assert task.status == "running"
    assert "pending_control" in task.params

    await apply_execution_telemetry(
        session, device, execution_id="exec-003", execution_state="paused", progress=41.0,
        completed_qty=None, result=None, failure_code=None,
    )

    assert execution.state == "paused"
    assert task.status == "paused"
    assert "pending_control" not in task.params


@pytest.mark.asyncio
async def test_cancel_confirmation_never_returns_task_to_scheduler() -> None:
    device = SimpleNamespace(id=uuid.uuid4(), status="working", operational_metrics={})
    task = SimpleNamespace(
        id=uuid.uuid4(),
        status="cancel_requested",
        progress=40.0,
        completed_qty=4.0,
        deliverable_qty=10.0,
        started_at=None,
        completed_at=None,
        cancelled_at=None,
        device_id=device.id,
        params={"cancellation": {"delivery": "queued"}},
        dispatch_state="cancelling",
        dispatch_reason="waiting_device_cancel",
        current_phase="working",
    )
    execution = SimpleNamespace(
        id=uuid.uuid4(),
        task_id=task.id,
        device_id=device.id,
        gateway_execution_id="exec-cancel-001",
        state="cancel_requested",
        phase="working",
        phase_sequence=0,
        phase_progress=40.0,
        phase_updated_at=None,
        progress=40.0,
        result={"control_return_state": "running"},
        failure_code=None,
        accepted_at=None,
        started_at=None,
        completed_at=None,
        completed_qty=4.0,
        allocation_id=None,
    )

    await apply_execution_telemetry(
        CancellationSession(execution, task),
        device,
        execution_id=execution.gateway_execution_id,
        execution_state="cancelled",
        progress=40.0,
        completed_qty=4.0,
        result=None,
        failure_code=None,
    )

    assert execution.state == "cancelled"
    assert task.status == "cancelled"
    assert task.dispatch_state == "cancelled"
    assert task.dispatch_reason == "operator_cancelled"
    assert task.cancelled_at is not None


@pytest.mark.asyncio
async def test_v1_running_telemetry_can_update_progress_repeatedly() -> None:
    device = _device()
    task = _task(device.id)
    execution = _execution(task, device)
    session = FakeSession(execution, task)

    await apply_execution_telemetry(
        session,
        device,
        execution_id=execution.gateway_execution_id,
        execution_state="running",
        progress=20.0,
        completed_qty=2.0,
        result=None,
        failure_code=None,
    )
    await apply_execution_telemetry(
        session,
        device,
        execution_id=execution.gateway_execution_id,
        execution_state="running",
        progress=35.0,
        completed_qty=3.5,
        result=None,
        failure_code=None,
    )

    assert execution.state == "running"
    assert execution.progress == 35.0
    assert task.progress == 35.0
    assert task.completed_qty == 3.5


@pytest.mark.asyncio
async def test_multi_device_allocation_telemetry_aggregates_before_completing_task() -> None:
    """One execution unit cannot finish the shared business task by itself."""

    device_a = _device()
    device_b = _device()
    task = _task(device_a.id)
    requirement_id = uuid.uuid4()
    requirement = SimpleNamespace(
        id=requirement_id,
        role_code="primary",
        output_unit="t",
        required_qty=10.0,
        completed_qty=0.0,
        is_completion_gate=True,
    )
    allocation_a = SimpleNamespace(
        id=uuid.uuid4(), requirement_id=requirement_id, planned_qty=6.0, completed_qty=0.0, state="running"
    )
    allocation_b = SimpleNamespace(
        id=uuid.uuid4(), requirement_id=requirement_id, planned_qty=4.0, completed_qty=0.0, state="running"
    )
    execution_a = _execution(task, device_a, state="running")
    execution_a.allocation_id = allocation_a.id
    execution_b = _execution(task, device_b, state="running")
    execution_b.allocation_id = allocation_b.id
    plan = SimpleNamespace(state="executing", reason=None)
    session = AllocationSession(task, [requirement], [allocation_a, allocation_b], plan)

    session.execution = execution_a
    await apply_execution_telemetry(
        session,
        device_a,
        execution_id=execution_a.gateway_execution_id,
        execution_state="completed",
        progress=100.0,
        completed_qty=6.0,
        result=None,
        failure_code=None,
    )

    assert task.status == "running"
    assert task.completed_qty == 6.0
    assert task.progress == 60.0
    assert allocation_a.state == "completed"
    assert allocation_b.state == "running"

    session.execution = execution_b
    await apply_execution_telemetry(
        session,
        device_b,
        execution_id=execution_b.gateway_execution_id,
        execution_state="completed",
        progress=100.0,
        completed_qty=4.0,
        result=None,
        failure_code=None,
    )

    assert task.status == "completed"
    assert task.completed_qty == 10.0
    assert task.progress == 100.0
    assert plan.state == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_phase", "current_sequence", "reported_phase", "reported_sequence", "message"),
    [
        ("navigating_to_target", 2, "navigating_to_target", 1, "阶段序号不能回退"),
        ("arrived_at_target", 3, "navigating_to_target", 4, "执行阶段不能回退"),
        ("navigating_to_target", 2, "working", 3, "不能回退或跳过"),
    ],
)
async def test_v2_rejects_invalid_phase_sequence_or_order(
    current_phase: str,
    current_sequence: int,
    reported_phase: str,
    reported_sequence: int,
    message: str,
) -> None:
    device = _device()
    task = _task(device.id)
    execution = _execution(
        task,
        device,
        protocol_version="v2",
        state="running",
        phase=current_phase,
        phase_sequence=current_sequence,
        phase_progress=50.0,
    )

    with pytest.raises(HTTPException) as error:
        await apply_execution_telemetry(
            FakeSession(execution, task),
            device,
            execution_id=execution.gateway_execution_id,
            execution_state="running",
            progress=50.0,
            completed_qty=None,
            result=None,
            failure_code=None,
            phase=reported_phase,
            phase_sequence=reported_sequence,
            phase_progress=50.0,
        )

    assert error.value.status_code == 409
    assert message in str(error.value.detail)


@pytest.mark.asyncio
async def test_v2_return_mission_requires_returned_phase() -> None:
    return_point_id = uuid.uuid4()
    device = _device()
    task = _task(device.id, return_policy="return_to_point", return_point_id=return_point_id)
    execution = _execution(
        task,
        device,
        protocol_version="v2",
        state="running",
        phase="returning",
        phase_sequence=6,
        phase_progress=80.0,
    )

    with pytest.raises(HTTPException) as error:
        await apply_execution_telemetry(
            FakeSession(execution, task),
            device,
            execution_id=execution.gateway_execution_id,
            execution_state="completed",
            progress=100.0,
            completed_qty=10.0,
            result={"return_completed": True, "return_point_id": str(return_point_id)},
            failure_code=None,
            phase="returning",
            phase_sequence=7,
            phase_progress=100.0,
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "mission_phase_incomplete"


@pytest.mark.asyncio
async def test_v2_return_mission_rejects_mismatched_return_evidence() -> None:
    return_point_id = uuid.uuid4()
    device = _device()
    task = _task(device.id, return_policy="return_to_point", return_point_id=return_point_id)
    execution = _execution(
        task,
        device,
        protocol_version="v2",
        state="running",
        phase="returning",
        phase_sequence=6,
        phase_progress=100.0,
    )

    with pytest.raises(HTTPException) as error:
        await apply_execution_telemetry(
            FakeSession(execution, task),
            device,
            execution_id=execution.gateway_execution_id,
            execution_state="completed",
            progress=100.0,
            completed_qty=10.0,
            result={"return_completed": True, "return_point_id": str(uuid.uuid4())},
            failure_code=None,
            phase="returned",
            phase_sequence=7,
            phase_progress=100.0,
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "return_not_confirmed"


@pytest.mark.asyncio
async def test_v2_return_mission_completes_after_matching_return_evidence() -> None:
    return_point_id = uuid.uuid4()
    device = _device()
    task = _task(device.id, return_policy="return_to_point", return_point_id=return_point_id)
    execution = _execution(
        task,
        device,
        protocol_version="v2",
        state="running",
        phase="returning",
        phase_sequence=6,
        phase_progress=100.0,
    )

    result = await apply_execution_telemetry(
        FakeSession(execution, task),
        device,
        execution_id=execution.gateway_execution_id,
        execution_state="completed",
        progress=100.0,
        completed_qty=10.0,
        result={"return_completed": True, "return_point_id": str(return_point_id)},
        failure_code=None,
        phase="returned",
        phase_sequence=7,
        phase_progress=100.0,
    )

    assert result is execution
    assert execution.state == "completed"
    assert execution.phase == "returned"
    assert task.status == "completed"
    assert task.current_phase == "returned"
    assert task.progress == 100.0
