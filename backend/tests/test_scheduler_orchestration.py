from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.scheduler.dag import DAGNode, TaskDAG
from app.scheduler.engine import SchedulerEngine
from app.models.models import MissionExecution


def _task(
    *,
    return_policy: str = "stay",
    target_device_types: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        process_id="material_transport",
        params={},
        map_point=SimpleNamespace(device_types=target_device_types or []),
        return_point=SimpleNamespace(device_types=[]),
        return_policy=return_policy,
        work_parameters={},
    )


def _device(*, capabilities: dict, protocol_version: str = "v2") -> SimpleNamespace:
    return SimpleNamespace(type="agv", capabilities=capabilities, protocol_version=protocol_version)


@pytest.mark.parametrize(
    ("task", "device"),
    [
        (_task(), _device(capabilities={})),
        (
            _task(return_policy="return_to_point"),
            _device(capabilities={"processes": ["material_transport"]}, protocol_version="v1"),
        ),
        (
            _task(target_device_types=["excavator"]),
            _device(capabilities={"processes": ["material_transport"]}),
        ),
    ],
    ids=["empty-capabilities", "v1-return-mission", "target-device-type"],
)
def test_scheduler_rejects_incompatible_devices(task: SimpleNamespace, device: SimpleNamespace) -> None:
    assert SchedulerEngine()._device_is_compatible(task, device) is False


def test_scheduler_accepts_explicitly_capable_v2_device() -> None:
    task = _task(return_policy="return_to_point")
    device = _device(capabilities={"processes": ["material_transport"]}, protocol_version="v2")

    assert SchedulerEngine()._device_is_compatible(task, device) is True


def test_site_prep_accepts_excavator_ground_leveling_capability() -> None:
    task = SimpleNamespace(
        process_id="site_prep",
        params={},
        map_point=SimpleNamespace(device_types=[]),
        return_point=None,
        return_policy="stay",
        work_parameters={},
    )
    device = SimpleNamespace(
        type="excavator",
        capabilities={"processes": ["excavation", "ground_leveling"]},
        protocol_version="v1",
    )

    assert SchedulerEngine()._device_is_compatible(task, device) is True


def test_resource_requirement_can_select_auxiliary_device_capability() -> None:
    """A transport allocation is valid even when the business task is excavation."""

    task = SimpleNamespace(
        process_id="pit_excavation",
        params={},
        map_point=SimpleNamespace(device_types=[]),
        return_point=None,
        return_policy="stay",
        work_parameters={},
    )
    transport_device = SimpleNamespace(
        type="agv",
        capabilities={"processes": ["material_transport"]},
        protocol_version="v2",
    )

    assert SchedulerEngine()._device_is_compatible(
        task,
        transport_device,
        capability_code="material_transport",
    ) is True


def test_inspection_device_alias_matches_inspection_process_and_point() -> None:
    task = SimpleNamespace(
        process_id="safety_inspect",
        params={},
        map_point=SimpleNamespace(device_types=["inspect"]),
        return_point=None,
        return_policy="stay",
        work_parameters={},
    )
    device = SimpleNamespace(
        type="inspection",
        capabilities={"processes": ["patrol_inspection"]},
        protocol_version="v1",
    )

    assert SchedulerEngine()._device_is_compatible(task, device) is True


def test_dag_rebuild_view_unlocks_pending_task_with_completed_dependency() -> None:
    dag = TaskDAG()
    dependency_id = "completed-task"
    dependent_id = "pending-task"
    dag.add_node(
        DAGNode(
            task_id=dependent_id,
            process_id="material_transport",
            name="待执行运输任务",
            status="pending",
            dependencies=[dependency_id],
        )
    )
    dag.add_node(
        DAGNode(
            task_id=dependency_id,
            process_id="site_prep",
            name="已完成前置任务",
            status="completed",
        )
    )

    assert [node.task_id for node in dag.get_ready_tasks()] == [dependent_id]


def test_dag_never_requeues_assigned_or_running_task() -> None:
    dag = TaskDAG()
    dag.add_node(DAGNode(task_id="pending", process_id="site_prep", name="待派发", status="pending"))
    dag.add_node(DAGNode(task_id="assigned", process_id="site_prep", name="已分配", status="assigned"))
    dag.add_node(DAGNode(task_id="running", process_id="site_prep", name="执行中", status="running"))

    assert [node.task_id for node in dag.get_ready_tasks()] == ["pending"]


@pytest.mark.asyncio
async def test_waiting_task_becomes_dispatchable_when_device_comes_online() -> None:
    device = SimpleNamespace(
        id=uuid.uuid4(),
        code="AGV-101",
        name="运输机器人",
        type="agv",
        capabilities={"processes": ["material_transport"]},
        protocol_version="v2",
        gateway_enabled=True,
        last_heartbeat=datetime.now(timezone.utc) - timedelta(minutes=5),
        status="idle",
        battery=80.0,
        position_x=0.0,
        position_y=0.0,
        position_z=0.0,
        health={},
        operational_metrics={},
    )
    task = _task()
    task.dispatch_state = "waiting_device"
    task.dispatch_reason = "compatible_devices_offline"

    class Result:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self

        def all(self):
            return self.values

    class Session:
        async def execute(self, statement):
            if statement.column_descriptions[0]["entity"] is MissionExecution:
                return Result([])
            if statement.column_descriptions[0]["name"] == "device_id":
                return Result([])
            return Result([device])

    engine = SchedulerEngine()
    candidates, reason = await engine._available_candidates(Session(), task, {"x": 1.0, "y": 1.0})
    assert candidates == []
    assert reason == "compatible_devices_offline"
    assert engine._set_dispatch_waiting(task, "waiting_device", reason) is False

    device.last_heartbeat = datetime.now(timezone.utc)
    candidates, reason = await engine._available_candidates(Session(), task, {"x": 1.0, "y": 1.0})
    assert [candidate["id"] for candidate in candidates] == [str(device.id)]
    assert reason == "awaiting_candidate"


def test_active_execution_indexes_allow_task_fleet_but_reserve_each_device() -> None:
    indexes = {index.name: index for index in MissionExecution.__table__.indexes}

    assert "uq_mission_executions_active_task" not in indexes
    assert indexes["uq_mission_executions_active_device"].unique is True
    assert indexes["uq_mission_executions_active_device"].dialect_options["postgresql"]["where"] is not None
