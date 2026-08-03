from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.models import Device, MissionExecution, TaskResourceAllocation, TaskResourcePlan, TaskResourceRequirement
from app.scheduler.resource_planner import plan_task_resources


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Result:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return _Scalars(self.values)


class PlannerSession:
    """In-memory query double for the planner's deterministic selection logic."""

    def __init__(self, plan, requirements, devices):
        self.plan = plan
        self.requirements = requirements
        self.devices = devices

    async def scalar(self, _statement):
        return self.plan

    async def execute(self, statement):
        description = statement.column_descriptions[0]
        entity = description.get('entity')
        if entity is TaskResourceRequirement:
            return _Result(self.requirements)
        if entity is TaskResourceAllocation:
            return _Result([])
        if entity is Device:
            return _Result(self.devices)
        if entity is MissionExecution:
            return _Result([])
        raise AssertionError(f'Unexpected planner query: {description}')

    def add(self, _item):
        raise AssertionError('The test supplies an existing resource plan.')

    async def flush(self):
        return None


def _capacity(capability_code: str, rate_per_hour: float) -> SimpleNamespace:
    return SimpleNamespace(
        capability_code=capability_code,
        output_unit='m3',
        rate_per_hour=rate_per_hour,
        valid_until=None,
    )


def _device(device_type: str, capability_code: str, rate_per_hour: float) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        code=f'{device_type}-{rate_per_hour:g}',
        type=device_type,
        capabilities={'processes': [capability_code]},
        protocol_version='v2',
        gateway_enabled=True,
        last_heartbeat=datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc),
        status='idle',
        battery=95.0,
        position_x=0.0,
        position_y=0.0,
        work_capacities=[_capacity(capability_code, rate_per_hour)],
    )


@pytest.mark.asyncio
async def test_capacity_planner_combines_different_device_types_for_multi_role_task() -> None:
    """A task becomes dispatchable only when all real work packages are covered."""

    task_id = uuid.uuid4()
    planning_at = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    excavation_requirement = SimpleNamespace(
        id=uuid.uuid4(),
        task_id=task_id,
        role_code='excavation',
        capability_code='excavation',
        required_qty=30.0,
        output_unit='m3',
        completed_qty=0.0,
        is_completion_gate=True,
        allocations=[],
    )
    transport_requirement = SimpleNamespace(
        id=uuid.uuid4(),
        task_id=task_id,
        role_code='transport',
        capability_code='material_transport',
        required_qty=30.0,
        output_unit='m3',
        completed_qty=0.0,
        is_completion_gate=True,
        allocations=[],
    )
    plan = SimpleNamespace(
        state='waiting_capacity',
        reason=None,
        window_start=None,
        window_end=None,
        required_rate_per_hour=None,
        planned_rate_per_hour=0.0,
        coverage_ratio=0.0,
        predicted_completion_at=None,
        summary={},
    )
    task = SimpleNamespace(
        id=task_id,
        process_id='pit_excavation',
        params={},
        deliverable_qty=30.0,
        deliverable_unit='m3',
        planned_start=planning_at,
        planned_end=planning_at + timedelta(hours=2),
        map_point=SimpleNamespace(x=0.0, y=0.0, device_types=[]),
        return_point=None,
        return_policy='stay',
        work_parameters={},
    )
    excavator = _device('excavator', 'excavation', 15.0)
    carrier = _device('agv', 'material_transport', 15.0)
    session = PlannerSession(plan, [excavation_requirement, transport_requirement], [excavator, carrier])

    decision = await plan_task_resources(session, task, at=planning_at)

    assert decision.is_sufficient is True
    assert decision.state == 'ready_to_dispatch'
    assert {(proposal.requirement.role_code, proposal.device.type) for proposal in decision.proposals} == {
        ('excavation', 'excavator'),
        ('transport', 'agv'),
    }
    assert {proposal.planned_qty for proposal in decision.proposals} == {30.0}
    assert plan.coverage_ratio == 1.0
