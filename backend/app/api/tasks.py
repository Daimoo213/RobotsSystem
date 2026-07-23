"""Tasks router — CRUD / reassign / pause / resume.

任务管理是 PM 端核心功能：发布任务 → 调度引擎分配设备 → 甘特图/待办列表实时更新。
任务创建后通过 WebSocket 广播，前端各面板自动刷新。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.redis import CHANNEL_EVENTS, CHANNEL_TASKS, redis
from app.core.security import require
from app.models.models import Device, MapPoint, MissionExecution, Script, Task
from app.services.fleet_commands import dispatch_mission, queue_command

router = APIRouter(prefix="/tasks", tags=["tasks"])
log = get_logger("api.tasks")


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


class TaskCreate(BaseModel):
    """任务发布请求——完整业务字段。"""
    name: str = Field(..., description="任务名称，用于调度台和设备任务记录展示。")
    process_id: str = Field(..., description="工序编码，必须取自工序选项接口返回的 29 项工序之一。")
    map_point_id: str | None = Field(None, description="目标施工点位 UUID；当前可调度任务必须提供且点位必须已存在。")
    priority: int = Field(50, description="任务优先级，约定范围 0 至 100；数值越大越优先。")
    estimated_duration: int = Field(60, description="预计执行时长，单位为分钟。")
    planned_start: datetime | None = Field(None, description="计划开始时间，使用带时区的 ISO 8601 时间。")
    planned_end: datetime | None = Field(None, description="计划结束时间；省略时可由计划开始时间和预计时长推导。")
    deliverable_qty: float | None = Field(None, description="计划交付工作量。")
    deliverable_unit: str | None = Field(None, description="交付工作量单位；省略时使用工序默认单位，例如 m³、车次、㎡或吨。")
    dependencies: list[str] = Field(default_factory=list, description="必须先完成的前置任务 UUID 字符串列表。")
    stage: str = Field("earthwork", description="施工阶段编码；默认 earthwork。")
    required_device_type: str | None = Field(None, description="执行任务所需的设备类型编码，用于点位兼容性和调度匹配。")
    params: dict = Field(default_factory=dict, description="传递给调度器和设备任务命令的业务扩展参数。")
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
    estimated_duration = req.estimated_duration or proc_info.get("duration", 60)

    # 自动计算 planned_end（如果只给了 start 和 duration）
    planned_start = req.planned_start
    planned_end = req.planned_end
    if planned_start and not planned_end and estimated_duration:
        from datetime import timedelta
        planned_end = planned_start + timedelta(minutes=estimated_duration)

    # A dispatchable job always targets a persisted, compatible project point.
    if not req.map_point_id:
        raise HTTPException(status_code=422, detail="map_point_id is required for dispatchable work")
    code = f"T-{uuid.uuid4().hex[:8].upper()}"
    map_point = await db.get(MapPoint, uuid.UUID(req.map_point_id))
    if map_point is None:
        raise HTTPException(status_code=400, detail="map point was not found")
    if req.required_device_type and map_point.device_types and req.required_device_type not in map_point.device_types:
        raise HTTPException(status_code=422, detail="map point is not compatible with required_device_type")

    active_script_result = await db.execute(select(Script).where(Script.is_active == True))
    active_script = active_script_result.scalar_one_or_none()

    task = Task(
        code=code,
        name=req.name,
        process_id=req.process_id,
        script_id=active_script.id if active_script else None,
        map_point_id=uuid.UUID(req.map_point_id),
        priority=req.priority,
        estimated_duration=estimated_duration,
        planned_start=planned_start,
        planned_end=planned_end,
        deliverable_qty=req.deliverable_qty,
        deliverable_unit=deliverable_unit,
        dependencies=req.dependencies,
        stage=stage,
        params={**req.params, "description": req.description, "required_device_type": req.required_device_type},
        status="pending",
    )
    task.map_point = map_point
    db.add(task)
    await db.flush()

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
    await db.flush()

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
    if device.status not in {"idle", "ready"}:
        raise HTTPException(status_code=409, detail="target device is not available")
    if device.battery < 20:
        raise HTTPException(status_code=409, detail="target device battery is below the dispatch threshold")
    required_type = str((t.params or {}).get("required_device_type") or "")
    if required_type and device.type != required_type:
        raise HTTPException(status_code=422, detail="target device type is not compatible with this task")
    supported_processes = (device.capabilities or {}).get("processes", [])
    if supported_processes and t.process_id not in supported_processes:
        raise HTTPException(status_code=422, detail="target device does not support this process")
    if t.map_point is None:
        t.map_point = await db.get(MapPoint, t.map_point_id)
    if t.map_point is None:
        raise HTTPException(status_code=409, detail="task target map point was not found")
    if active_execution:
        old_device = await db.get(Device, active_execution.device_id)
        if old_device:
            await queue_command(
                db, old_device, "mission_cancel", source="operator", priority=90,
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
        t.params = {
            **(t.params or {}),
            "pending_reassignment": {
                "target_device_id": str(device.id),
                "requested_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    else:
        await dispatch_mission(
            db,
            t,
            device,
            {"x": t.map_point.x, "y": t.map_point.y, "z": t.map_point.z},
        )
    await db.flush()
    task_dict = _task_dict(t)
    await _broadcast_task_change(t, "task_updated")
    return task_dict


@router.post(
    "/{task_id}/pause",
    summary="请求暂停施工任务",
    description="为任务当前执行设备写入暂停命令，并将执行实例标记为等待设备确认；响应不表示设备已暂停。",
    response_description="返回命令入队状态和任务当前信息。",
)
async def pause_task(task_id: Annotated[uuid.UUID, Path(description="待暂停任务的 UUID。")], db: AsyncSession = Depends(get_db),
                     _role=Depends(require("task.pause"))) -> dict:
    result = await db.execute(select(Task).where(Task.id == task_id))
    t = result.scalar_one_or_none()
    if t:
        if t.device_id:
            device = await db.get(Device, t.device_id)
            execution = await db.scalar(
                select(MissionExecution)
                .where(MissionExecution.task_id == t.id, MissionExecution.state.in_(["dispatched", "accepted", "running"]))
                .order_by(MissionExecution.dispatched_at.desc())
            )
            if device is None or execution is None:
                raise HTTPException(status_code=409, detail="task has no active mission to pause")
            await queue_command(
                db, device, "mission_pause", source="operator", priority=90,
                idempotency_key=f"mission-pause:{execution.id}",
                payload={"execution_id": execution.gateway_execution_id},
                mission_execution_id=execution.id,
            )
            execution.result = {**(execution.result or {}), "control_return_state": execution.state}
            execution.state = "pause_requested"
            t.params = {
                **(t.params or {}),
                "pending_control": {"action": "pause", "execution_id": execution.gateway_execution_id},
            }
        else:
            raise HTTPException(status_code=409, detail="task has not been dispatched")
        await db.flush()
        _ = await _broadcast_task_change(t, "task_paused")
        return {"ok": True, "delivery": "queued", "task": _task_dict(t)}
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
        if t.device_id:
            device = await db.get(Device, t.device_id)
            execution = await db.scalar(
                select(MissionExecution)
                .where(MissionExecution.task_id == t.id, MissionExecution.state == "paused")
                .order_by(MissionExecution.dispatched_at.desc())
            )
            if device is None or execution is None:
                raise HTTPException(status_code=409, detail="task has no paused mission to resume")
            await queue_command(
                db, device, "mission_resume", source="operator", priority=90,
                idempotency_key=f"mission-resume:{execution.id}",
                payload={"execution_id": execution.gateway_execution_id},
                mission_execution_id=execution.id,
            )
            execution.result = {**(execution.result or {}), "control_return_state": execution.state}
            execution.state = "resume_requested"
            t.params = {
                **(t.params or {}),
                "pending_control": {"action": "resume", "execution_id": execution.gateway_execution_id},
            }
        else:
            raise HTTPException(status_code=409, detail="task has not been dispatched")
        await db.flush()
        _ = await _broadcast_task_change(t, "task_resumed")
        return {"ok": True, "delivery": "queued", "task": _task_dict(t)}
    raise HTTPException(status_code=404, detail="task not found")


@router.delete(
    "/{task_id}",
    summary="删除施工任务",
    description="删除指定任务记录，并通过 WebSocket 广播任务删除事件。重复删除不存在的任务仍返回成功。",
    response_description="返回任务删除操作结果。",
)
async def delete_task(task_id: Annotated[uuid.UUID, Path(description="待删除任务的 UUID。")], db: AsyncSession = Depends(get_db),
                      _role=Depends(require("task.update"))) -> dict:
    """删除任务（PM权限）。"""
    result = await db.execute(select(Task).where(Task.id == task_id))
    t = result.scalar_one_or_none()
    if t:
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
    return {
        "id": str(t.id),
        "code": t.code,
        "name": t.name,
        "process_id": t.process_id,
        "device_id": str(t.device_id) if t.device_id else None,
        "device_code": device.code if device else None,
        "status": t.status,
        "priority": t.priority,
        "map_point_id": str(t.map_point_id) if t.map_point_id else None,
        "map_point_code": map_point.code if map_point else None,
        "map_point_name": map_point.name if map_point else None,
        "progress": t.progress,
        "dependencies": t.dependencies or [],
        "estimated_duration": t.estimated_duration,
        "planned_start": t.planned_start.isoformat() if t.planned_start else None,
        "planned_end": t.planned_end.isoformat() if t.planned_end else None,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "deliverable_qty": t.deliverable_qty,
        "deliverable_unit": t.deliverable_unit,
        "completed_qty": t.completed_qty,
        "stage": t.stage,
        "params": t.params or {},
    }
