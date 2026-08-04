from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api import tasks as task_api
from app.models.models import Device, MissionExecution, Task, TaskResourceAllocation


class _SingleResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _ManyResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return SimpleNamespace(all=lambda: self.values)


class PauseSession:
    def __init__(self, task, execution, device, allocation, start_priority):
        self.task = task
        self.execution = execution
        self.device = device
        self.allocation = allocation
        self.start_priority = start_priority

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is Task:
            return _SingleResult(self.task)
        if entity is MissionExecution:
            return _ManyResult([self.execution])
        raise AssertionError(f"unexpected query entity: {entity}")

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return self.task if entity is Task else self.start_priority

    async def get(self, model, _identifier):
        if model is Device:
            return self.device
        if model is TaskResourceAllocation:
            return self.allocation
        raise AssertionError(f"unexpected model lookup: {model}")

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_pause_assigned_mission_follows_its_start_command(monkeypatch) -> None:
    task = SimpleNamespace(id=uuid.uuid4(), params={})
    device = SimpleNamespace(id=uuid.uuid4())
    allocation = SimpleNamespace(id=uuid.uuid4(), state="dispatched")
    execution = SimpleNamespace(
        id=uuid.uuid4(),
        device_id=device.id,
        allocation_id=allocation.id,
        gateway_execution_id="exec-assigned-001",
        state="dispatched",
        result={},
    )
    session = PauseSession(task, execution, device, allocation, start_priority=47)
    queued: list[dict] = []

    async def fake_queue_command(_db, _device, command, **kwargs):
        queued.append({"command": command, **kwargs})
        return SimpleNamespace(id=uuid.uuid4())

    async def fake_broadcast(_task, _change_type):
        return None

    monkeypatch.setattr(task_api, "queue_command", fake_queue_command)
    monkeypatch.setattr(task_api, "_broadcast_task_change", fake_broadcast)
    monkeypatch.setattr(task_api, "_task_dict", lambda value: {"id": str(value.id)})

    response = await task_api.pause_task(task.id, db=session, _role=None)

    assert response["ok"] is True
    assert execution.state == "pause_requested"
    assert allocation.state == "pause_requested"
    assert queued == [{
        "command": "mission_pause",
        "source": "operator",
        "priority": 47,
        "idempotency_key": f"mission-pause:{execution.id}",
        "payload": {"execution_id": "exec-assigned-001"},
        "mission_execution_id": execution.id,
    }]


@pytest.mark.asyncio
async def test_cancel_assigned_mission_follows_its_start_command(monkeypatch) -> None:
    task = SimpleNamespace(
        id=uuid.uuid4(),
        status="assigned",
        params={},
        dispatch_state="dispatched",
        dispatch_reason=None,
    )
    device = SimpleNamespace(id=uuid.uuid4())
    allocation = SimpleNamespace(id=uuid.uuid4(), state="dispatched")
    execution = SimpleNamespace(
        id=uuid.uuid4(),
        device_id=device.id,
        allocation_id=allocation.id,
        gateway_execution_id="exec-assigned-cancel-001",
        state="dispatched",
        result={},
    )
    session = PauseSession(task, execution, device, allocation, start_priority=47)
    queued: list[dict] = []

    async def fake_queue_command(_db, _device, command, **kwargs):
        queued.append({"command": command, **kwargs})
        return SimpleNamespace(id=uuid.uuid4())

    async def fake_broadcast(_task, _change_type):
        return None

    monkeypatch.setattr(task_api, "queue_command", fake_queue_command)
    monkeypatch.setattr(task_api, "_broadcast_task_change", fake_broadcast)
    monkeypatch.setattr(task_api, "_task_dict", lambda value: {"id": str(value.id)})

    response = await task_api.cancel_task(task.id, db=session, _role=None)

    assert response["ok"] is True
    assert execution.state == "cancel_requested"
    assert allocation.state == "cancel_requested"
    assert queued == [{
        "command": "mission_cancel",
        "source": "operator",
        "priority": 47,
        "idempotency_key": f"mission-cancel:{execution.id}",
        "payload": {"execution_id": "exec-assigned-cancel-001", "reason": "task_cancelled_by_operator"},
        "mission_execution_id": execution.id,
    }]
