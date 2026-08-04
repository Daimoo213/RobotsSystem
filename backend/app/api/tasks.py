"""Tasks router — CRUD / reassign / pause / resume.

任务管理是 PM 端核心功能：发布任务 → 调度引擎分配设备 → 甘特图/待办列表实时更新。
任务创建后通过 WebSocket 广播，前端各面板自动刷新。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import CHANNEL_EVENTS, CHANNEL_TASKS, redis
from app.core.security import require
from app.models.models import Device, DeviceCommand, MapPoint, MissionExecution, Script, Task, TaskResourceAllocation, TaskResourcePlan, TaskResourceRequirement
from app.scheduler.matching import device_is_compatible
from app.scheduler.resource_planner import plan_task_resources
from app.scheduler.scheduling import automatic_schedule_window, completed_dependency_anchor
from app.services.fleet_commands import build_mission_navigation, dispatch_mission, queue_command

router = APIRouter(prefix="/tasks", tags=["tasks"])
log = get_logger("api.tasks")

ACTIVE_EXECUTION_STATES = (
    "dispatched",
    "accepted",
    "running",
    "paused",
    "pause_requested",
    "resume_requested",
    "cancel_requested",
)

TASK_RESPONSE_OPTIONS = (
    selectinload(Task.device),
    selectinload(Task.map_point),
    selectinload(Task.return_point),
    selectinload(Task.resource_plan),
    selectinload(Task.resource_requirements),
    selectinload(Task.resource_allocations).selectinload(TaskResourceAllocation.device),
    selectinload(Task.resource_allocations).selectinload(TaskResourceAllocation.executions),
)


async def _mission_control_priority(
    db: AsyncSession,
    execution: MissionExecution,
    *,
    default: int = 90,
) -> int:
    """Preserve FIFO order when controlling an execution not yet started."""

    if execution.state != "dispatched":
        return default
    start_priority = await db.scalar(
        select(DeviceCommand.priority)
        .where(
            DeviceCommand.mission_execution_id == execution.id,
            DeviceCommand.command == "mission_start",
        )
        .order_by(DeviceCommand.created_at.desc())
        .limit(1)
    )
    return start_priority if start_priority is not None else default


async def _load_task_response(db: AsyncSession, task_id: uuid.UUID) -> Task:
    """Load a task and every relationship used by the response serializer."""

    task = await db.scalar(
        select(Task)
        .where(Task.id == task_id)
        .options(*TASK_RESPONSE_OPTIONS)
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise RuntimeError(f"task {task_id} disappeared before its response was built")
    return task


@router.get(
    "",
    summary="查询施工任务列表",
    description="查询真实施工任务，可按任务状态和施工阶段同时筛选，结果按优先级及计划时间排序。",
    response_description="返回符合筛选条件的施工任务列表。",
)
async def list_tasks(
    status_filter: str | None = Query(None, alias="status", description="任务状态编码；省略时不按状态筛选。"),
    stage: str | None = Query(None, description="施工阶段编码；省略时不按施工阶段筛选。"),
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("read")),
) -> list[dict]:
    stmt = select(Task)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    if stage:
        stmt = stmt.where(Task.stage == stage)
    result = await db.execute(stmt.order_by(Task.priority.desc(), Task.planned_start, Task.created_at))
    return [_task_dict(t) for t in result.scalars().all()]


@router.get(
    "/{task_id:uuid}",
    summary="查询施工任务详情",
    description="按任务 UUID 查询任务基本信息、计划、目标点位、分配设备、进度及交付量。",
    response_description="返回指定施工任务的当前完整信息。",
)
async def get_task(task_id: Annotated[uuid.UUID, Path(description="目标任务的 UUID。")], db: AsyncSession = Depends(get_db),
                   _role=Depends(require("read"))) -> dict:
    result = await db.execute(select(Task).where(Task.id == task_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="task not found")
    return _task_dict(t)


# ── 工序选项（供前端下拉）──────────────────────────────
PROCESS_OPTIONS = [
    {"id": "site_prep", "name": "场地平整", "stage": "earthwork", "unit": "㎡", "duration": 60},
    {"id": "pit_excavation", "name": "基坑土方清运", "stage": "earthwork", "unit": "m³", "duration": 120},
    {"id": "spoil_export", "name": "渣土外运", "stage": "earthwork", "unit": "m³", "duration": 90},
    {"id": "pile_foundation", "name": "桩基施工", "stage": "foundation", "unit": "m³", "duration": 180},
    {"id": "rebar_binding", "name": "钢筋绑扎", "stage": "main", "unit": "t", "duration": 100},
    {"id": "formwork", "name": "模板安装", "stage": "main", "unit": "㎡", "duration": 80},
    {"id": "concrete_pouring", "name": "混凝土浇筑", "stage": "main", "unit": "m³", "duration": 120},
    {"id": "concrete_curing", "name": "混凝土养护", "stage": "main", "unit": "天", "duration": 720},
    {"id": "precast_hoisting", "name": "预制构件吊装", "stage": "main", "unit": "t", "duration": 60},
    {"id": "rebar_processing", "name": "钢筋加工配送", "stage": "main", "unit": "t", "duration": 90},
    {"id": "masonry_wall", "name": "楼层砌筑", "stage": "main", "unit": "㎡", "duration": 100},
    {"id": "vertical_transport", "name": "楼层垂直运输", "stage": "main", "unit": "t", "duration": 40},
    {"id": "pipe_install", "name": "管线安装", "stage": "mep", "unit": "m", "duration": 60},
    {"id": "cable_tray", "name": "桥架安装", "stage": "mep", "unit": "m", "duration": 50},
    {"id": "cable_laying", "name": "电缆敷设", "stage": "mep", "unit": "m", "duration": 50},
    {"id": "plastering", "name": "内墙抹灰", "stage": "finishing", "unit": "㎡", "duration": 80},
    {"id": "wall_spray", "name": "墙面喷涂", "stage": "finishing", "unit": "㎡", "duration": 60},
    {"id": "floor_grinding", "name": "地坪打磨找平", "stage": "finishing", "unit": "㎡", "duration": 70},
    {"id": "wall_grinding", "name": "墙面打磨", "stage": "finishing", "unit": "㎡", "duration": 50},
    {"id": "tile_paving", "name": "瓷砖铺贴", "stage": "finishing", "unit": "㎡", "duration": 90},
    {"id": "ceiling_install", "name": "吊顶安装", "stage": "finishing", "unit": "㎡", "duration": 80},
    {"id": "material_transport", "name": "建材辅料转运", "stage": "earthwork", "unit": "t", "duration": 30},
    {"id": "waste_removal", "name": "施工垃圾清运", "stage": "earthwork", "unit": "m³", "duration": 45},
    {"id": "site_tidy", "name": "场地文明规整", "stage": "earthwork", "unit": "㎡", "duration": 30},
    {"id": "safety_inspect", "name": "现场安全巡检", "stage": "earthwork", "unit": "km", "duration": 20},
    {"id": "edge_guard", "name": "临边看护巡查", "stage": "earthwork", "unit": "km", "duration": 15},
    {"id": "emergency_supply", "name": "应急抢险补给", "stage": "earthwork", "unit": "t", "duration": 30},
    {"id": "surveying", "name": "测量放线", "stage": "earthwork", "unit": "m", "duration": 40},
    {"id": "quality_check", "name": "质量检测", "stage": "earthwork", "unit": "㎡", "duration": 30},
]


@router.get(
    "/meta/processes",
    summary="查询支持的施工工序",
    description="返回系统支持的 29 项施工工序及其阶段、默认交付单位和默认预估时长。",
    response_description="返回可用于创建任务的工序选项列表。",
)
async def list_processes(_role=Depends(require("read"))) -> list[dict]:
    """返回29项工序选项，供前端任务发布表单下拉使用。"""
    return PROCESS_OPTIONS


class TaskResourceRequirementCreate(BaseModel):
    """One work package that the capacity planner must cover with real devices."""

    model_config = ConfigDict(extra="forbid")

    role_code: str = Field(min_length=1, max_length=64, description="任务内资源角色编码，例如 primary、earthwork 或 transport。")
    capability_code: str = Field(min_length=1, max_length=64, description="设备必须声明的工序或能力编码。")
    required_qty: float = Field(gt=0, description="该资源角色必须完成的真实工作量。")
    output_unit: str = Field(min_length=1, max_length=32, description="该资源角色工作量单位，必须与设备登记产能单位一致。")
    is_completion_gate: bool = Field(default=True, description="为 true 时该角色未达量不能完成业务任务。")
    work_scope: dict[str, Any] = Field(
        default_factory=dict,
        description="该角色的真实作业范围、区域分片或队列约束；平台原样下发给设备执行单元。",
    )


class TaskCreate(BaseModel):
    """任务发布请求——完整业务字段。"""
    name: str = Field(..., description="任务名称，用于调度台和设备任务记录展示。")
    process_id: str = Field(..., description="工序编码，必须取自工序选项接口返回的 29 项工序之一。")
    map_point_id: uuid.UUID | None = Field(None, description="目标施工点位 UUID；当前可调度任务必须提供且点位必须已存在。")
    priority: int = Field(50, description="任务优先级，约定范围 0 至 100；数值越大越优先。")
    estimated_duration: int | None = Field(None, ge=1, description="预计执行时长，单位为分钟；省略时使用所选工序的默认工时。")
    schedule_mode: Literal["auto", "fixed"] = Field(
        "auto",
        description="排期方式：auto 根据当前时间或前置任务结束时间自动排期；fixed 使用人工指定的计划开始时间。",
    )
    planned_start: datetime | None = Field(None, description="计划开始时间，使用带时区的 ISO 8601 时间。")
    planned_end: datetime | None = Field(None, description="计划结束时间；省略时可由计划开始时间和预计时长推导。")
    deliverable_qty: float | None = Field(None, description="计划交付工作量。")
    deliverable_unit: str | None = Field(None, description="交付工作量单位；省略时使用工序默认单位，例如 m³、车次、㎡或吨。")
    dependencies: list[uuid.UUID] = Field(default_factory=list, description="必须先完成的前置任务 UUID 列表。")
    stage: str = Field("earthwork", description="施工阶段编码；默认 earthwork。")
    required_device_type: str | None = Field(None, description="执行任务所需的设备类型编码，用于点位兼容性和调度匹配。")
    work_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="仅下发给 v2 机器人作业控制器的结构化工序参数；不得包含平台内部控制字段。",
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="导航、作业或现场限制条件，由机器人项目按工序协议校验和执行。",
    )
    return_policy: Literal["stay", "return_to_point"] = Field(
        default="stay",
        description="作业结束后的处置策略：stay 原地结束，return_to_point 返回指定地图点位后结束。",
    )
    return_point_id: uuid.UUID | None = Field(
        default=None,
        description="return_to_point 策略使用的停车、待机或充电点位 UUID。",
    )
    resource_requirements: list[TaskResourceRequirementCreate] = Field(
        default_factory=list,
        description="可选的多角色资源需求；省略时按任务工序和交付量创建一个主作业需求。",
    )
    description: str | None = Field(None, description="任务业务说明或现场备注。")


@router.post(
    "",
    summary="创建施工任务",
    description=(
        "创建真实施工任务并写入数据库，校验目标点位和设备类型兼容性。"
        "创建成功后任务进入调度 DAG，并通过 WebSocket 通知前端；设备分配由后续调度周期完成。"
    ),
    response_description="返回已创建任务的完整信息和服务端生成的任务编码。",
)
async def create_task(
    req: Annotated[TaskCreate, Body(description="待创建施工任务的计划、点位、工序和调度要求。")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("task.create")),
) -> dict:
    """创建施工任务（PM权限）。

    任务创建后：
    1. 写入数据库
    2. 加入调度引擎 DAG（调度器下个 tick 自动分配设备）
    3. 通过 WebSocket 广播 tasks + events 频道
    4. 前端甘特图、待办列表自动刷新
    """
    # 查找工序信息，自动填充默认值
    proc_info = next((p for p in PROCESS_OPTIONS if p["id"] == req.process_id), None)
    if not proc_info:
        raise HTTPException(status_code=400, detail=f"unknown process_id: {req.process_id}")

    # 自动推导 stage
    stage = req.stage or proc_info["stage"]
    # 自动推导 deliverable_unit
    deliverable_unit = req.deliverable_unit or proc_info.get("unit")
    # 自动推导 estimated_duration
    estimated_duration = req.estimated_duration if req.estimated_duration is not None else proc_info.get("duration", 60)

    # Validate explicit fixed windows before resolving dependency-based auto scheduling.
    planned_start = req.planned_start
    planned_end = req.planned_end
    if planned_start and planned_start.tzinfo is None:
        raise HTTPException(status_code=422, detail="planned_start must include a timezone")
    if planned_end and planned_end.tzinfo is None:
        raise HTTPException(status_code=422, detail="planned_end must include a timezone")
    if req.schedule_mode == "fixed":
        if planned_start is None:
            raise HTTPException(status_code=422, detail="固定排期必须提供带时区的计划开始时间")
        if planned_end is None:
            planned_end = planned_start + timedelta(minutes=estimated_duration)
        if planned_end <= planned_start:
            raise HTTPException(status_code=422, detail="计划结束时间必须晚于计划开始时间")
    elif planned_start is not None or planned_end is not None:
        raise HTTPException(status_code=422, detail="自动排期不接受人工计划起止时间，请使用固定排期")

    # A dispatchable job always targets a persisted, compatible project point.
    if not req.map_point_id:
        raise HTTPException(status_code=422, detail="map_point_id is required for dispatchable work")
    code = f"T-{uuid.uuid4().hex[:8].upper()}"
    map_point = await db.get(MapPoint, req.map_point_id)
    if map_point is None:
        raise HTTPException(status_code=400, detail="map point was not found")
    if req.required_device_type and map_point.device_types and req.required_device_type not in map_point.device_types:
        raise HTTPException(status_code=422, detail="map point is not compatible with required_device_type")

    if len(set(req.dependencies)) != len(req.dependencies):
        raise HTTPException(status_code=422, detail="dependencies contains duplicate task ids")
    dependency_tasks: list[Task] = []
    if req.dependencies:
        dependency_tasks = (
            await db.execute(select(Task).where(Task.id.in_(req.dependencies)))
        ).scalars().all()
        if len(dependency_tasks) != len(req.dependencies):
            raise HTTPException(status_code=422, detail="one or more dependency tasks were not found")

    active_script_result = await db.execute(select(Script).where(Script.is_active == True))
    active_script = active_script_result.scalar_one_or_none()
    if active_script:
        invalid_dependencies = [
            dependency
            for dependency in dependency_tasks
            if dependency.status != "completed" and dependency.script_id != active_script.id
        ]
        if invalid_dependencies:
            raise HTTPException(
                status_code=422,
                detail="unfinished dependency tasks must belong to the active construction script",
            )

    current_time = datetime.now(timezone.utc)
    auto_schedule_anchor = None
    if req.schedule_mode == "auto":
        planned_start, planned_end = automatic_schedule_window(dependency_tasks, estimated_duration, current_time)
        dependency_anchor = completed_dependency_anchor(dependency_tasks)
        auto_schedule_anchor = dependency_anchor.isoformat() if dependency_anchor else None

    return_point = None
    if req.return_policy == "return_to_point":
        if req.return_point_id is None:
            raise HTTPException(status_code=422, detail="return_point_id is required for return_to_point")
        if req.return_point_id == req.map_point_id:
            raise HTTPException(status_code=422, detail="return point must be different from the work target")
        return_point = await db.get(MapPoint, req.return_point_id)
        if return_point is None:
            raise HTTPException(status_code=400, detail="return point was not found")
        if return_point.point_type not in {"parking", "standby", "charge"}:
            raise HTTPException(status_code=422, detail="return point must be a parking, standby, or charge point")
    elif req.return_point_id is not None:
        raise HTTPException(status_code=422, detail="return_point_id is only valid with return_to_point")

    has_incomplete_dependency = any(dependency.status != "completed" for dependency in dependency_tasks)
    dispatch_state = "waiting_dependencies" if has_incomplete_dependency else "waiting_device"
    dispatch_reason = "dependencies_incomplete" if has_incomplete_dependency else "awaiting_candidate"
    if not has_incomplete_dependency and planned_start and planned_start > current_time:
        dispatch_state = "waiting_schedule"
        dispatch_reason = "planned_start_not_reached"

    task = Task(
        code=code,
        name=req.name,
        process_id=req.process_id,
        script_id=active_script.id if active_script else None,
        map_point_id=req.map_point_id,
        return_point_id=req.return_point_id,
        return_policy=req.return_policy,
        work_parameters=req.work_parameters,
        dispatch_state=dispatch_state,
        dispatch_reason=dispatch_reason,
        priority=req.priority,
        estimated_duration=estimated_duration,
        schedule_mode=req.schedule_mode,
        planned_start=planned_start,
        planned_end=planned_end,
        deliverable_qty=req.deliverable_qty,
        deliverable_unit=deliverable_unit,
        dependencies=[str(dependency_id) for dependency_id in req.dependencies],
        stage=stage,
        params={
            "description": req.description,
            "required_device_type": req.required_device_type,
            "constraints": req.constraints,
            "auto_schedule_anchor": auto_schedule_anchor,
        },
        status="pending",
    )
    task.map_point = map_point
    task.return_point = return_point
    db.add(task)
    await db.flush()
    if req.resource_requirements:
        db.add_all(
            [
                TaskResourceRequirement(
                    task_id=task.id,
                    task=task,
                    role_code=requirement.role_code,
                    capability_code=requirement.capability_code,
                    required_qty=requirement.required_qty,
                    output_unit=requirement.output_unit,
                    is_completion_gate=requirement.is_completion_gate,
                    work_scope=requirement.work_scope,
                )
                for requirement in req.resource_requirements
            ]
        )
        await db.flush()
    await plan_task_resources(db, task)
    await db.flush()

    # Newly created ORM instances do not have selectin relationships populated.
    # Reload before serializing so no async lazy load occurs outside SQLAlchemy's IO context.
    task = await _load_task_response(db, task.id)
    task_dict = _task_dict(task)
    log.info("task.created", code=code, name=req.name, process_id=req.process_id)

    # ── 广播任务变更到 WebSocket ────────────────────────
    r = redis()
    await r.publish(CHANNEL_TASKS, json.dumps({
        "channel": CHANNEL_TASKS,
        "data": {"type": "task_created", **task_dict},
    }, default=str))
    await r.publish(CHANNEL_EVENTS, json.dumps({
        "channel": CHANNEL_EVENTS,
        "data": {
            "time": datetime.now(timezone.utc).isoformat(),
            "type": "task_created",
            "message": f"新任务 {code} {req.name} 已发布，等待调度分配设备",
        },
    }, default=str))

    # ── 通知调度引擎加载新任务 ──────────────────────────
    from app.services.runtime import get_runtime
    runtime = get_runtime()
    if runtime and runtime.scheduler:
        from app.scheduler.dag import DAGNode
        node = DAGNode(
            task_id=str(task.id),
            process_id=task.process_id,
            name=task.name,
            status="pending",
            dependencies=task.dependencies or [],
            priority=task.priority,
            map_point_id=str(task.map_point_id) if task.map_point_id else None,
            estimated_duration=task.estimated_duration,
            stage=task.stage,
            planned_start=task.planned_start,
        )
        runtime.scheduler.dag.add_node(node)
        log.info("task.added_to_dag", code=code)

    return task_dict


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, description="新的任务名称；省略或传 null 时保持原值。")
    priority: int | None = Field(default=None, description="新的任务优先级；省略或传 null 时保持原值。")
    planned_start: datetime | None = Field(default=None, description="新的计划开始时间；省略或传 null 时保持原值。")
    planned_end: datetime | None = Field(default=None, description="新的计划结束时间；省略或传 null 时保持原值。")
    deliverable_qty: float | None = Field(default=None, description="新的计划交付工作量；省略或传 null 时保持原值。")
    deliverable_unit: str | None = Field(default=None, description="新的计划交付量单位；省略或传 null 时保持原值。")


@router.patch(
    "/{task_id}",
    summary="更新施工任务",
    description="更新任务名称、优先级、计划时间或计划交付量；未提供的字段保持不变。",
    response_description="返回更新后的施工任务完整信息。",
)
async def update_task(
    task_id: Annotated[uuid.UUID, Path(description="目标任务的 UUID。")],
    req: Annotated[TaskUpdate, Body(description="需要更新的任务字段；未提供的字段保持不变。")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("task.update")),
) -> dict:
    result = await db.execute(select(Task).where(Task.id == task_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="task not found")
    if req.name is not None:
        t.name = req.name
    if req.priority is not None:
        t.priority = req.priority
    if req.planned_start is not None:
        t.planned_start = req.planned_start
    if req.planned_end is not None:
        t.planned_end = req.planned_end
    if req.deliverable_qty is not None:
        t.deliverable_qty = req.deliverable_qty
    if req.deliverable_unit is not None:
        t.deliverable_unit = req.deliverable_unit
    await plan_task_resources(db, t)
    await db.flush()

    from app.services.runtime import get_runtime
    runtime = get_runtime()
    if runtime and runtime.scheduler:
        runtime.scheduler.dag.update_task(
            str(t.id),
            name=t.name,
            priority=t.priority,
            planned_start=t.planned_start,
        )

    task_dict = _task_dict(t)
    # 广播更新
    r = redis()
    await r.publish(CHANNEL_TASKS, json.dumps({
        "channel": CHANNEL_TASKS,
        "data": {"type": "task_updated", **task_dict},
    }, default=str))

    return task_dict


@router.post(
    "/{task_id}/reassign",
    summary="改派施工任务设备",
    description=(
        "将任务改派给另一台已启用且空闲的兼容设备。若原任务正在执行，先向原设备下发取消命令，"
        "待设备遥测确认后再完成改派；无活动执行实例时直接创建新的任务执行。"
    ),
    response_description="返回进入改派流程后的任务当前信息。",
)
async def reassign_task(
    task_id: Annotated[uuid.UUID, Path(description="待改派任务的 UUID。")],
    device_id: uuid.UUID = Query(..., description="接收任务的目标设备 UUID。"),
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("task.reassign")),
) -> dict:
    """改派任务到另一台设备（PM权限）。"""
    result = await db.execute(select(Task).where(Task.id == task_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="task not found")
    has_resource_requirements = await db.scalar(
        select(TaskResourceRequirement.id).where(TaskResourceRequirement.task_id == t.id).limit(1)
    )
    if has_resource_requirements is not None:
        raise HTTPException(
            status_code=409,
            detail="该任务由多设备资源计划管理，请重新计算资源计划，由系统按剩余工作量重新调度。",
        )
    device = await db.get(Device, device_id)
    if device is None or not device.gateway_enabled:
        raise HTTPException(status_code=404, detail="target device was not found or is disabled")
    active_execution = await db.scalar(
        select(MissionExecution)
        .where(
            MissionExecution.task_id == t.id,
            MissionExecution.state.in_([
                "dispatched", "accepted", "running", "paused",
                "pause_requested", "resume_requested", "cancel_requested",
            ]),
        )
        .order_by(MissionExecution.dispatched_at.desc())
    )
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.gateway_offline_after_seconds)
    if not device.last_heartbeat or device.last_heartbeat < cutoff:
        raise HTTPException(status_code=409, detail="target device is offline")
    if device.status not in {"idle", "ready"}:
        raise HTTPException(status_code=409, detail="target device is not available")
    if device.battery < settings.low_battery_threshold:
        raise HTTPException(status_code=409, detail="target device battery is below the dispatch threshold")
    if t.map_point is None:
        t.map_point = await db.get(MapPoint, t.map_point_id)
    if t.map_point is None:
        raise HTTPException(status_code=409, detail="task target map point was not found")
    if t.return_point_id:
        return_point = await db.get(MapPoint, t.return_point_id)
        if return_point is None:
            raise HTTPException(status_code=409, detail="task return point was not found")
        t.return_point = return_point
    if not device_is_compatible(t, device):
        raise HTTPException(status_code=422, detail="target device is not compatible with this task")
    device_active_execution = await db.scalar(
        select(MissionExecution.id).where(
            MissionExecution.device_id == device.id,
            MissionExecution.state.in_([
                "dispatched", "accepted", "running", "paused",
                "pause_requested", "resume_requested", "cancel_requested",
            ]),
        )
    )
    if device_active_execution is not None:
        raise HTTPException(status_code=409, detail="target device already has an active mission")
    if active_execution:
        old_device = await db.get(Device, active_execution.device_id)
        if old_device:
            await queue_command(
                db, old_device, "mission_cancel", source="operator",
                priority=await _mission_control_priority(db, active_execution),
                idempotency_key=f"mission-cancel:{active_execution.id}",
                payload={"execution_id": active_execution.gateway_execution_id, "reason": "reassign"},
                mission_execution_id=active_execution.id,
            )
        active_execution.result = {
            **(active_execution.result or {}),
            "control_return_state": active_execution.state,
            "reassignment_target_device_id": str(device.id),
        }
        active_execution.state = "cancel_requested"
        t.status = "reassign_pending"
        t.dispatch_state = "waiting_device"
        t.dispatch_reason = "waiting_previous_device_cancel"
        t.params = {
            **(t.params or {}),
            "pending_reassignment": {
                "target_device_id": str(device.id),
                "requested_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    else:
        target, return_plan = await build_mission_navigation(db, t)
        await dispatch_mission(db, t, device, target, return_plan)
    await db.flush()
    task_dict = _task_dict(t)
    await _broadcast_task_change(t, "task_updated")
    return task_dict


@router.post(
    "/{task_id}/resource-plan/recalculate",
    summary="重新计算任务资源计划",
    description="根据任务真实交付量、计划窗口和设备网关登记的有效产能重新计算设备类型、数量与产能缺口；不会伪造设备或立即改变设备遥测状态。",
    response_description="返回任务最新的资源计划、资源需求和已下发执行单元。",
)
async def recalculate_resource_plan(
    task_id: Annotated[uuid.UUID, Path(description="待重新规划资源的任务 UUID。")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("task.update")),
) -> dict:
    task = await db.scalar(
        select(Task)
        .where(Task.id == task_id)
        .options(selectinload(Task.map_point), selectinload(Task.return_point))
        .with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    await plan_task_resources(db, task)
    await db.flush()
    payload = _task_dict(task)
    await _broadcast_task_change(task, "task_resource_plan_updated")
    return payload


@router.post(
    "/{task_id}/pause",
    summary="请求暂停施工任务",
    description=(
        "为任务当前执行设备写入暂停命令，并将执行实例标记为等待设备确认；"
        "已下发但尚未启动的任务会让暂停命令排在对应启动命令之后送达，响应不表示设备已暂停。"
    ),
    response_description="返回命令入队状态和任务当前信息。",
)
async def pause_task(task_id: Annotated[uuid.UUID, Path(description="待暂停任务的 UUID。")], db: AsyncSession = Depends(get_db),
                     _role=Depends(require("task.pause"))) -> dict:
    result = await db.execute(select(Task).where(Task.id == task_id))
    t = result.scalar_one_or_none()
    if t:
        executions = (
            await db.execute(
                select(MissionExecution)
                .where(MissionExecution.task_id == t.id, MissionExecution.state.in_(["dispatched", "accepted", "running"]))
                .order_by(MissionExecution.dispatched_at)
            )
        ).scalars().all()
        if not executions:
            raise HTTPException(status_code=409, detail="task has no active mission to pause")
        command_ids: list[str] = []
        for execution in executions:
            device = await db.get(Device, execution.device_id)
            if device is None:
                raise HTTPException(status_code=409, detail="task has an execution without a registered device")

            # A dispatched execution already has a mission_start command. Keep the
            # same priority so FIFO delivery sends start before this control for
            # the same execution instance.
            command_priority = await _mission_control_priority(db, execution)

            command = await queue_command(
                db, device, "mission_pause", source="operator", priority=command_priority,
                idempotency_key=f"mission-pause:{execution.id}",
                payload={"execution_id": execution.gateway_execution_id},
                mission_execution_id=execution.id,
            )
            execution.result = {**(execution.result or {}), "control_return_state": execution.state}
            execution.state = "pause_requested"
            if execution.allocation_id is not None:
                allocation = await db.get(TaskResourceAllocation, execution.allocation_id)
                if allocation is not None:
                    allocation.state = "pause_requested"
            command_ids.append(str(command.id))
        t.params = {
            **(t.params or {}),
            "pending_controls": {"action": "pause", "execution_ids": [execution.gateway_execution_id for execution in executions]},
        }
        await db.flush()
        _ = await _broadcast_task_change(t, "task_paused")
        return {"ok": True, "delivery": "queued", "execution_ids": command_ids, "task": _task_dict(t)}
    raise HTTPException(status_code=404, detail="task not found")


@router.post(
    "/{task_id}/resume",
    summary="请求恢复施工任务",
    description="为已暂停任务的执行设备写入恢复命令，并等待设备遥测确认；响应不表示设备已恢复执行。",
    response_description="返回命令入队状态和任务当前信息。",
)
async def resume_task(task_id: Annotated[uuid.UUID, Path(description="待恢复任务的 UUID。")], db: AsyncSession = Depends(get_db),
                      _role=Depends(require("task.resume"))) -> dict:
    result = await db.execute(select(Task).where(Task.id == task_id))
    t = result.scalar_one_or_none()
    if t:
        executions = (
            await db.execute(
                select(MissionExecution)
                .where(MissionExecution.task_id == t.id, MissionExecution.state == "paused")
                .order_by(MissionExecution.dispatched_at)
            )
        ).scalars().all()
        if not executions:
            raise HTTPException(status_code=409, detail="task has no paused mission to resume")
        command_ids: list[str] = []
        for execution in executions:
            device = await db.get(Device, execution.device_id)
            if device is None:
                raise HTTPException(status_code=409, detail="task has an execution without a registered device")
            command = await queue_command(
                db, device, "mission_resume", source="operator", priority=90,
                idempotency_key=f"mission-resume:{execution.id}",
                payload={"execution_id": execution.gateway_execution_id},
                mission_execution_id=execution.id,
            )
            execution.result = {**(execution.result or {}), "control_return_state": execution.state}
            execution.state = "resume_requested"
            if execution.allocation_id is not None:
                allocation = await db.get(TaskResourceAllocation, execution.allocation_id)
                if allocation is not None:
                    allocation.state = "resume_requested"
            command_ids.append(str(command.id))
        t.params = {
            **(t.params or {}),
            "pending_controls": {"action": "resume", "execution_ids": [execution.gateway_execution_id for execution in executions]},
        }
        await db.flush()
        _ = await _broadcast_task_change(t, "task_resumed")
        return {"ok": True, "delivery": "queued", "execution_ids": command_ids, "task": _task_dict(t)}
    raise HTTPException(status_code=404, detail="task not found")


@router.post(
    "/{task_id}/cancel",
    summary="安全取消施工任务",
    description=(
        "请求取消任务。平台会向该任务的每个活动执行单元写入幂等 mission_cancel 命令，"
        "已下发但尚未启动的执行单元会让取消命令排在对应启动命令之后送达；"
        "并保持取消中状态，直到对应设备通过遥测确认停止。没有活动执行单元的待调度任务会立即标记为已取消。"
    ),
    response_description="返回取消命令入队结果和任务当前状态；命令入队不代表设备已经停止。",
)
async def cancel_task(
    task_id: Annotated[uuid.UUID, Path(description="待取消任务的 UUID。")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("task.update")),
) -> dict:
    """Request a durable, telemetry-confirmed cancellation for one task."""

    task = await db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status == "cancelled":
        raise HTTPException(status_code=409, detail="任务已经取消")
    if task.status == "completed":
        raise HTTPException(status_code=409, detail="已完成任务不能取消")

    executions = (
        await db.execute(
            select(MissionExecution)
            .where(
                MissionExecution.task_id == task.id,
                MissionExecution.state.in_(ACTIVE_EXECUTION_STATES),
            )
            .order_by(MissionExecution.dispatched_at)
        )
    ).scalars().all()
    command_ids: list[str] = []
    requested_at = datetime.now(timezone.utc)

    if not executions:
        allocations = (
            await db.execute(
                select(TaskResourceAllocation).where(
                    TaskResourceAllocation.task_id == task.id,
                    TaskResourceAllocation.state.in_(
                        ("planned", "dispatched", "accepted", "running", "paused", "pause_requested", "resume_requested", "cancel_requested")
                    ),
                )
            )
        ).scalars().all()
        for allocation in allocations:
            allocation.state = "cancelled"
        plan = await db.scalar(select(TaskResourcePlan).where(TaskResourcePlan.task_id == task.id))
        if plan is not None:
            plan.state = "cancelled"
            plan.reason = "operator_cancelled"
        task.status = "cancelled"
        task.dispatch_state = "cancelled"
        task.dispatch_reason = "operator_cancelled"
        task.cancelled_at = requested_at
        task.device_id = None
        task.params = {
            **(task.params or {}),
            "cancellation": {"requested_at": requested_at.isoformat(), "delivery": "not_required"},
        }
        await db.flush()
        await _broadcast_task_change(task, "task_cancelled")
        return {"ok": True, "delivery": "not_required", "command_ids": [], "task": _task_dict(task)}

    for execution in executions:
        device = await db.get(Device, execution.device_id)
        if device is None:
            raise HTTPException(status_code=409, detail="任务存在未登记设备的活动执行单元，无法安全取消")
        command = await queue_command(
            db,
            device,
            "mission_cancel",
            source="operator",
            priority=await _mission_control_priority(db, execution),
            idempotency_key=f"mission-cancel:{execution.id}",
            payload={"execution_id": execution.gateway_execution_id, "reason": "task_cancelled_by_operator"},
            mission_execution_id=execution.id,
        )
        command_ids.append(str(command.id))
        if execution.state != "cancel_requested":
            execution.result = {**(execution.result or {}), "control_return_state": execution.state}
            execution.state = "cancel_requested"
        if execution.allocation_id is not None:
            allocation = await db.get(TaskResourceAllocation, execution.allocation_id)
            if allocation is not None:
                allocation.state = "cancel_requested"

    task.status = "cancel_requested"
    task.dispatch_state = "cancelling"
    task.dispatch_reason = "waiting_device_cancel"
    task.params = {
        **(task.params or {}),
        "cancellation": {
            "requested_at": requested_at.isoformat(),
            "delivery": "queued",
            "execution_ids": [execution.gateway_execution_id for execution in executions],
        },
    }
    await db.flush()
    await _broadcast_task_change(task, "task_cancel_requested")
    return {"ok": True, "delivery": "queued", "command_ids": command_ids, "task": _task_dict(task)}


@router.delete(
    "/{task_id}",
    summary="删除未下发施工任务",
    description=(
        "仅删除从未产生执行历史、尚未下发且没有下游依赖的任务。已下发或已执行任务必须使用取消接口，"
        "由设备遥测确认停止后保留审计记录。"
    ),
    response_description="返回任务删除操作结果。",
)
async def delete_task(task_id: Annotated[uuid.UUID, Path(description="待删除任务的 UUID。")], db: AsyncSession = Depends(get_db),
                      _role=Depends(require("task.update"))) -> dict:
    """Physically delete only an unissued task with no execution history."""
    result = await db.execute(select(Task).where(Task.id == task_id).with_for_update())
    t = result.scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    has_execution = await db.scalar(
        select(MissionExecution.id).where(MissionExecution.task_id == t.id).limit(1)
    )
    dependent_task_id = await db.scalar(
        select(Task.id).where(Task.dependencies.contains([str(t.id)])).limit(1)
    )
    if t.status != "pending" or has_execution is not None:
        raise HTTPException(status_code=409, detail="任务已进入调度或执行历史，不能删除；请使用取消任务")
    if dependent_task_id is not None:
        raise HTTPException(status_code=409, detail="该任务被其他任务作为前置依赖，调整下游依赖后才能删除")
    from app.services.runtime import get_runtime
    runtime = get_runtime()
    if runtime and runtime.scheduler:
        runtime.scheduler.dag.remove_node(str(t.id))
    await db.delete(t)
    await db.flush()
    r = redis()
    await r.publish(CHANNEL_TASKS, json.dumps({
        "channel": CHANNEL_TASKS,
        "data": {"type": "task_deleted", "task_id": str(task_id)},
    }, default=str))
    return {"ok": True}


async def _broadcast_task_change(t: Task, change_type: str) -> None:
    """广播任务变更到 WebSocket。"""
    r = redis()
    await r.publish(CHANNEL_TASKS, json.dumps({
        "channel": CHANNEL_TASKS,
        "data": {"type": change_type, **_task_dict(t)},
    }, default=str))


def _task_dict(t: Task) -> dict:
    device = t.__dict__.get("device")
    map_point = t.__dict__.get("map_point")
    return_point = t.__dict__.get("return_point")
    plan = t.resource_plan
    requirements = t.resource_requirements or []
    allocations = t.resource_allocations or []
    return {
        "id": str(t.id),
        "code": t.code,
        "name": t.name,
        "process_id": t.process_id,
        "device_id": str(t.device_id) if t.device_id else None,
        "device_code": device.code if device else None,
        "status": t.status,
        "priority": t.priority,
        "schedule_mode": t.schedule_mode,
        "map_point_id": str(t.map_point_id) if t.map_point_id else None,
        "map_point_code": map_point.code if map_point else None,
        "map_point_name": map_point.name if map_point else None,
        "return_policy": t.return_policy,
        "return_point_id": str(t.return_point_id) if t.return_point_id else None,
        "return_point_code": return_point.code if return_point else None,
        "return_point_name": return_point.name if return_point else None,
        "work_parameters": t.work_parameters or {},
        "dispatch_state": t.dispatch_state,
        "dispatch_reason": t.dispatch_reason,
        "dispatch_attempts": t.dispatch_attempts,
        "last_dispatch_attempt_at": t.last_dispatch_attempt_at.isoformat() if t.last_dispatch_attempt_at else None,
        "current_phase": t.current_phase,
        "progress": t.progress,
        "dependencies": t.dependencies or [],
        "estimated_duration": t.estimated_duration,
        "planned_start": t.planned_start.isoformat() if t.planned_start else None,
        "planned_end": t.planned_end.isoformat() if t.planned_end else None,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "cancelled_at": t.cancelled_at.isoformat() if t.cancelled_at else None,
        "deliverable_qty": t.deliverable_qty,
        "deliverable_unit": t.deliverable_unit,
        "completed_qty": t.completed_qty,
        "stage": t.stage,
        "params": t.params or {},
        "resource_plan": _resource_plan_dict(plan),
        "resource_requirements": [_resource_requirement_dict(requirement) for requirement in requirements],
        "resource_allocations": [_resource_allocation_dict(allocation) for allocation in allocations],
    }


def _resource_plan_dict(plan: TaskResourcePlan | None) -> dict | None:
    if plan is None:
        return None
    return {
        "state": plan.state,
        "reason": plan.reason,
        "revision": plan.revision,
        "window_start": plan.window_start.isoformat() if plan.window_start else None,
        "window_end": plan.window_end.isoformat() if plan.window_end else None,
        "required_rate_per_hour": plan.required_rate_per_hour,
        "planned_rate_per_hour": plan.planned_rate_per_hour,
        "coverage_ratio": plan.coverage_ratio,
        "predicted_completion_at": plan.predicted_completion_at.isoformat() if plan.predicted_completion_at else None,
        "generated_at": plan.generated_at.isoformat() if plan.generated_at else None,
        "summary": plan.summary or {},
    }


def _resource_requirement_dict(requirement: TaskResourceRequirement) -> dict:
    return {
        "id": str(requirement.id),
        "role_code": requirement.role_code,
        "capability_code": requirement.capability_code,
        "required_qty": requirement.required_qty,
        "completed_qty": requirement.completed_qty,
        "output_unit": requirement.output_unit,
        "is_completion_gate": requirement.is_completion_gate,
        "work_scope": requirement.work_scope or {},
    }


def _resource_allocation_dict(allocation: TaskResourceAllocation) -> dict:
    device = allocation.__dict__.get("device")
    execution = next(iter(allocation.__dict__.get("executions") or []), None)
    return {
        "id": str(allocation.id),
        "requirement_id": str(allocation.requirement_id),
        "device_id": str(allocation.device_id),
        "device_code": device.code if device else None,
        "device_type": device.type if device else None,
        "plan_revision": allocation.plan_revision,
        "planned_qty": allocation.planned_qty,
        "completed_qty": allocation.completed_qty,
        "output_unit": allocation.output_unit,
        "rate_per_hour_snapshot": allocation.rate_per_hour_snapshot,
        "capacity_source": allocation.capacity_source,
        "capacity_evidence_ref": allocation.capacity_evidence_ref,
        "capacity_reported_at": allocation.capacity_reported_at.isoformat(),
        "work_scope": allocation.work_scope or {},
        "available_from": allocation.available_from.isoformat(),
        "predicted_finish_at": allocation.predicted_finish_at.isoformat() if allocation.predicted_finish_at else None,
        "state": allocation.state,
        "execution_id": execution.gateway_execution_id if execution else None,
        "execution_phase": execution.phase if execution else None,
        "execution_progress": execution.progress if execution else None,
    }
