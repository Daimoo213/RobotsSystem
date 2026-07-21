from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.fleet_commands import apply_execution_telemetry


class FakeSession:
    def __init__(self, execution, task):
        self.execution = execution
        self.task = task

    async def scalar(self, _statement):
        return self.execution

    async def get(self, model, _identifier):
        return self.task if model.__name__ == "Task" else None


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
