"""Devices router — list / detail / command."""

from __future__ import annotations

import json
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require
from app.models.models import Alert, Device, DeviceCommand, DeviceEvent, MaintenanceWorkOrder, MissionExecution, Task
from app.services.runtime import ESTOP_STATE_KEY, get_runtime
from app.services.fleet_commands import apply_execution_telemetry, queue_command

router = APIRouter(prefix="/devices", tags=["devices"])

PENDING_COMMAND_STATUSES = ("pending", "delivered")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def require_gateway_api_key(
    x_device_gateway_key: str | None = Header(
        default=None,
        description="设备接入网关共享 API 密钥，对应服务端 DEVICE_GATEWAY_API_KEY 配置。",
    ),
) -> None:
    """Authenticate a robot gateway without sharing operator JWT credentials."""
    if not settings.device_gateway_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="device gateway API key is not configured",
        )
    if not x_device_gateway_key or not secrets.compare_digest(
        x_device_gateway_key, settings.device_gateway_api_key
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid device gateway API key")


class GatewayPosition(BaseModel):
    x: float = Field(description="地图坐标系中的 X 坐标，单位为米。")
    y: float = Field(description="地图坐标系中的 Y 坐标，单位为米。")
    z: float = Field(default=0.0, description="地图坐标系中的 Z 坐标，单位为米。")


class GatewayRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32, description="设备唯一编码；注册后作为网关接口中的 device_code 使用。")
    name: str = Field(min_length=1, max_length=64, description="设备显示名称。")
    type: str = Field(min_length=1, max_length=32, description="设备类型编码，用于调度匹配和设备筛选。")
    model: str | None = Field(default=None, max_length=64, description="设备厂商型号；未知时可省略。")
    capabilities: dict[str, Any] = Field(
        default_factory=dict,
        description="设备能力声明；支持的工序可通过 processes 字符串数组提供。",
    )
    section_tags: dict[str, Any] = Field(default_factory=dict, description="设备所属区域或业务分组标签。")
    permissions: dict[str, Any] = Field(default_factory=dict, description="设备侧声明的操作权限或限制条件。")
    section_id: str | None = Field(default=None, max_length=32, description="设备当前所属施工区域编码。")
    health: dict[str, Any] = Field(default_factory=dict, description="设备注册时上报的真实健康状态。")
    protocol_version: str = Field(default="v1", max_length=32, description="设备网关协议版本。")


class GatewayMissionUpdate(BaseModel):
    execution_id: str = Field(min_length=1, max_length=96, description="任务下发命令中携带的执行实例标识。")
    state: Literal["accepted", "running", "paused", "completed", "failed", "cancelled"] = Field(
        description="设备确认的任务执行状态。"
    )
    progress: float | None = Field(default=None, ge=0, le=100, description="任务执行进度百分比，范围 0 至 100。")
    completed_qty: float | None = Field(default=None, ge=0, description="已完成工作量，单位沿用对应任务的交付单位。")
    result: dict[str, Any] | None = Field(default=None, description="任务完成或终止时的结构化执行结果。")
    failure_code: str | None = Field(default=None, max_length=96, description="任务失败原因编码；非失败状态可省略。")
    estimated_completion_at: datetime | None = Field(default=None, description="设备预计完成时间，使用带时区的 ISO 8601 时间。")


class GatewayOperationalMetrics(BaseModel):
    """Measurements reported by a physical robot or external bridge.

    Values are intentionally optional: device vendors expose different sensor
    sets. Omitted values are never estimated by the control plane.
    """

    power_kw: float | None = Field(default=None, ge=0, description="设备当前实测功率，单位为 kW。")
    energy_kwh_total: float | None = Field(default=None, ge=0, description="设备累计实测能耗，单位为 kWh。")
    mileage_km_total: float | None = Field(default=None, ge=0, description="设备累计行驶里程，单位为 km。")
    runtime_hours_total: float | None = Field(default=None, ge=0, description="设备累计运行时长，单位为小时。")
    payload_ratio: float | None = Field(default=None, ge=0, le=1, description="设备当前载荷率，范围 0 至 1。")
    localization_drift_meters: float | None = Field(default=None, ge=0, description="设备当前定位漂移量，单位为米。")


class GatewayTelemetry(BaseModel):
    """Gateway-neutral telemetry. Additional vendor metrics are retained in the event payload."""

    model_config = ConfigDict(extra="allow")

    event_id: str = Field(min_length=1, max_length=96, description="遥测事件幂等标识；同一设备重复上报相同值时不会重复写入。")
    boot_id: str = Field(min_length=1, max_length=96, description="设备本次启动实例标识；每次设备或网关重启后应更换。")
    sequence: int = Field(ge=0, description="本次启动实例内单调递增的遥测序号。")
    frame_id: str = Field(default="map", min_length=1, max_length=64, description="position 坐标采用的坐标系名称。")
    schema_version: str = Field(default="v1", min_length=1, max_length=32, description="遥测数据结构版本。")
    status: str | None = Field(default=None, min_length=1, max_length=16, description="设备当前运行状态编码。")
    battery: float | None = Field(default=None, ge=0, le=100, description="设备剩余电量百分比，范围 0 至 100。")
    position: GatewayPosition | None = Field(default=None, description="设备在指定坐标系中的当前位置。")
    section_id: str | None = Field(default=None, max_length=32, description="设备当前所在施工区域编码。")
    health: dict[str, Any] | None = Field(default=None, description="设备真实健康检查结果；未提供的指标不会由服务端推测。")
    metrics: GatewayOperationalMetrics | None = Field(default=None, description="设备实测运行指标。")
    observed_at: datetime | None = Field(default=None, description="设备采样时间，使用带时区的 ISO 8601 时间；省略时以服务端接收时间为准。")
    mission: GatewayMissionUpdate | None = Field(default=None, description="当前任务执行状态更新；无执行任务时可省略。")


class GatewayCommandAck(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["acknowledged", "failed"] = Field(
        description="命令处理结果：acknowledged 表示设备已成功处理命令，failed 表示处理失败；任务实际状态仍以 mission 遥测为准。"
    )
    message: str | None = Field(default=None, max_length=512, description="设备返回的执行结果或失败原因说明。")


class GatewayCalibrationReport(BaseModel):
    event_id: str = Field(min_length=1, max_length=96, description="校准事件幂等标识。")
    qrcode_id: str | None = Field(default=None, max_length=96, description="自动校准使用的二维码或定位标记标识。")
    source: Literal["automatic", "manual"] = Field(description="校准来源：automatic 为设备自动校准，manual 为人工触发校准。")
    observed_at: datetime = Field(description="设备完成校准的时间，使用带时区的 ISO 8601 时间。")
    success: bool = Field(description="校准是否成功。")
    position: GatewayPosition | None = Field(default=None, description="校准成功后设备确认的实际位置。")
    drift_meters: float | None = Field(default=None, ge=0, description="校准前检测到的定位漂移量，单位为米。")
    message: str | None = Field(default=None, max_length=512, description="校准结果或失败原因说明。")


async def _gateway_device(db: AsyncSession, device_code: str) -> Device:
    result = await db.execute(select(Device).where(Device.code == device_code))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="device is not registered")
    return device


def _hash_gateway_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _require_device_key(db: AsyncSession, device_code: str, provided_key: str | None) -> Device:
    device = await _gateway_device(db, device_code)
    if not provided_key or not device.gateway_key_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="device gateway credential is required")
    if not secrets.compare_digest(_hash_gateway_key(provided_key), device.gateway_key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid device gateway credential")
    if not device.gateway_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="device gateway is disabled")
    return device


async def _global_estop_state() -> tuple[bool, str | None]:
    """Read the runtime latch and its Redis cycle identifier when available."""
    runtime = get_runtime()
    if runtime is None or not runtime.estop_active:
        return False, None

    try:
        from app.core.redis import redis

        raw_state = await redis().get(ESTOP_STATE_KEY)
        if raw_state:
            state = json.loads(raw_state)
            if state.get("active"):
                return True, str(state.get("triggered_at") or "runtime")
    except Exception:
        # The in-process latch remains authoritative if Redis is temporarily unavailable.
        pass
    return True, "runtime"


async def _queue_command(
    db: AsyncSession,
    device: Device,
    command: str,
    payload: dict[str, Any] | None = None,
) -> DeviceCommand:
    return await queue_command(db, device, command, payload=payload, source="system")


async def _ensure_global_estop_command(
    db: AsyncSession,
    device: Device,
    estop_cycle: str,
) -> None:
    """Queue one durable stop command for each active emergency-stop cycle."""
    result = await db.execute(
        select(DeviceCommand)
        .where(DeviceCommand.device_id == device.id, DeviceCommand.command == "estop")
        .order_by(DeviceCommand.created_at.desc())
        .limit(20)
    )
    global_command = next(
        (
            command
            for command in result.scalars().all()
            if command.payload.get("scope") == "global"
            and command.payload.get("estop_cycle") == estop_cycle
        ),
        None,
    )
    if global_command is None:
        await queue_command(
            db,
            device,
            "estop",
            payload={"scope": "global", "estop_cycle": estop_cycle},
            source="safety",
            priority=100,
            idempotency_key=f"estop:{estop_cycle}:{device.id}",
        )
    elif global_command.status == "failed":
        global_command.status = "pending"
        global_command.delivered_at = None
        db.add(
            DeviceEvent(
                time=_now(),
                device_id=device.id,
                event_type="command_retry",
                payload={"command_id": str(global_command.id), "command": "estop"},
            )
        )


async def _last_sequence(
    db: AsyncSession,
    device_id: uuid.UUID,
    boot_id: str,
) -> int | None:
    """Return the most recent accepted telemetry sequence for one boot epoch."""

    result = await db.execute(
        select(DeviceEvent.sequence)
        .where(
            DeviceEvent.device_id == device_id,
            DeviceEvent.boot_id == boot_id,
            DeviceEvent.event_type == "telemetry",
        )
        .order_by(DeviceEvent.sequence.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _metrics_dict(metrics: GatewayOperationalMetrics | None) -> dict[str, Any]:
    return metrics.model_dump(exclude_none=True) if metrics else {}


async def _create_maintenance_reminders(db: AsyncSession, device: Device) -> None:
    """Create one durable work order per configured, actually reported threshold."""

    rules = (
        ("runtime_hours", settings.maintenance_runtime_hours_threshold, "runtime_hours_total"),
        ("mileage_km", settings.maintenance_mileage_km_threshold, "mileage_km_total"),
    )
    for trigger_type, threshold, metric_name in rules:
        raw_value = (device.operational_metrics or {}).get(metric_name)
        if threshold is None or raw_value is None or float(raw_value) < threshold:
            continue
        existing = await db.scalar(
            select(MaintenanceWorkOrder.id).where(
                MaintenanceWorkOrder.device_id == device.id,
                MaintenanceWorkOrder.trigger_type == trigger_type,
                MaintenanceWorkOrder.status.in_(["open", "ack"]),
            )
        )
        if existing is not None:
            continue
        work_order = MaintenanceWorkOrder(
            device_id=device.id,
            trigger_type=trigger_type,
            threshold=threshold,
            observed_value=float(raw_value),
            note=f"Reported {metric_name} reached the configured maintenance threshold.",
        )
        db.add(work_order)
        await db.flush()
        db.add(
            Alert(
                device_id=device.id,
                level="warning",
                category="maintenance_due",
                message=f"Device {device.code} requires maintenance based on {trigger_type}.",
                payload={"work_order_id": str(work_order.id), "threshold": threshold, "observed_value": float(raw_value)},
            )
        )


def _command_dict(command: DeviceCommand) -> dict:
    return {
        "id": str(command.id),
        "command": command.command,
        "payload": command.payload,
        "created_at": command.created_at.isoformat(),
        "idempotency_key": command.idempotency_key,
        "priority": command.priority,
    }


async def _publish_device_snapshot(db: AsyncSession) -> None:
    """Notify browser dashboards after a gateway changes device state."""

    try:
        from app.core.redis import CHANNEL_DEVICES, redis

        result = await db.execute(select(Device).order_by(Device.code))
        payload = {"channel": CHANNEL_DEVICES, "data": {"devices": [_device_dict(device) for device in result.scalars()]}}
        await redis().publish(CHANNEL_DEVICES, json.dumps(payload, default=str))
    except Exception:
        # Gateway ingestion remains durable even if the dashboard broker is unavailable.
        return


@router.post(
    "/gateway/register",
    summary="注册或更新机器人设备",
    description=(
        "首次注册使用系统级设备网关密钥；成功后仅在本次响应中返回设备专属密钥。"
        "已注册设备再次调用时必须使用该设备的专属密钥。"
    ),
    response_description="返回注册结果、设备当前信息，以及首次注册时生成的设备专属密钥。",
)
async def register_gateway_device(
    req: Annotated[GatewayRegistration, Body(description="机器人设备注册信息和能力声明。")],
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: str | None = Header(
        default=None,
        description="首次注册时填写系统级设备网关密钥；更新已注册设备时填写该设备的专属密钥。",
    ),
) -> dict:
    """Enroll one device, then require its bound credential for later updates."""
    result = await db.execute(select(Device).where(Device.code == req.code))
    device = result.scalar_one_or_none()
    created = device is None
    enrollment_key: str | None = None
    health = {"connection": "ok", **req.health}
    if device is None:
        await require_gateway_api_key(x_device_gateway_key)
        device = Device(
            code=req.code,
            name=req.name,
            type=req.type,
            model=req.model,
            capabilities=req.capabilities,
            section_tags=req.section_tags,
            permissions=req.permissions,
            section_id=req.section_id,
            health=health,
            status="idle",
            last_heartbeat=_now(),
            gateway_key_hash=_hash_gateway_key(enrollment_key := secrets.token_urlsafe(32)),
        )
        db.add(device)
    else:
        await _require_device_key(db, req.code, x_device_gateway_key)
        device.name = req.name
        device.type = req.type
        device.model = req.model
        device.capabilities = req.capabilities
        device.section_tags = req.section_tags
        device.permissions = req.permissions
        device.section_id = req.section_id
        device.health = health
        device.last_heartbeat = _now()
    await db.flush()
    db.add(
        DeviceEvent(
            time=_now(),
            device_id=device.id,
            event_type="registration",
            payload={"created": created, "model": device.model, "capabilities": device.capabilities},
        )
    )
    await db.commit()
    await _publish_device_snapshot(db)
    return {
        "created": created,
        "device": _device_dict(device),
        # Returned exactly once during bootstrap. Store it in the robot/Gazebo bridge secret store.
        "device_gateway_key": enrollment_key,
    }


@router.post(
    "/gateway/{device_code}/telemetry",
    summary="上报机器人遥测数据",
    description=(
        "接收真实机器人或外部仿真桥接程序上报的心跳、位置、电量、健康状态、运行指标及任务进度。"
        "event_id 用于幂等去重，sequence 必须在同一 boot_id 内单调递增。"
    ),
    response_description="返回遥测接收结果、设备最新状态、急停状态及关联的任务执行标识。",
)
async def report_gateway_telemetry(
    device_code: Annotated[str, Path(description="已注册设备的唯一编码。")],
    req: Annotated[GatewayTelemetry, Body(description="机器人本次采样的遥测、健康状态和任务执行信息。")],
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: str | None = Header(default=None, description="设备首次注册时获得的专属网关密钥。"),
) -> dict:
    """Persist a device heartbeat and the latest operational state."""
    device = await _require_device_key(db, device_code, x_device_gateway_key)
    received_at = _now()
    if req.observed_at and req.observed_at > received_at + timedelta(seconds=settings.gateway_telemetry_future_tolerance_seconds):
        raise HTTPException(status_code=422, detail="observed_at exceeds allowed future tolerance")
    duplicate = await db.scalar(
        select(DeviceEvent).where(DeviceEvent.device_id == device.id, DeviceEvent.event_id == req.event_id)
    )
    if duplicate:
        return {"ok": True, "duplicate": True, "device": _device_dict(device)}
    last_sequence = await _last_sequence(db, device.id, req.boot_id)
    if last_sequence is not None and req.sequence <= last_sequence:
        raise HTTPException(
            status_code=409,
            detail=f"telemetry sequence must increase within boot_id {req.boot_id}",
        )
    estop_active, _ = await _global_estop_state()
    reported_status = req.status
    if req.status is not None and not estop_active:
        device.status = req.status
    elif estop_active:
        device.status = "paused"
    if req.battery is not None:
        device.battery = req.battery
    if req.position is not None:
        device.position_x = req.position.x
        device.position_y = req.position.y
        device.position_z = req.position.z
    if req.section_id is not None:
        device.section_id = req.section_id
    if req.health is not None:
        device.health = {"connection": "ok", **req.health}
    else:
        device.health = {**device.health, "connection": "ok"}
    if req.metrics is not None:
        device.operational_metrics = {**device.operational_metrics, **_metrics_dict(req.metrics)}
        await _create_maintenance_reminders(db, device)
    device.last_heartbeat = received_at

    payload = req.model_dump(mode="json", exclude_none=True)
    payload["global_estop_active"] = estop_active
    if estop_active and reported_status is not None:
        payload["reported_status"] = reported_status
    execution = None
    if req.mission:
        execution = await apply_execution_telemetry(
            db,
            device,
            execution_id=req.mission.execution_id,
            execution_state=req.mission.state,
            progress=req.mission.progress,
            completed_qty=req.mission.completed_qty,
            result=req.mission.result,
            failure_code=req.mission.failure_code,
            estimated_completion_at=req.mission.estimated_completion_at,
        )
    db.add(
        DeviceEvent(
            time=received_at,
            device_id=device.id,
            event_type="telemetry",
            event_id=req.event_id,
            boot_id=req.boot_id,
            sequence=req.sequence,
            received_at=received_at,
            payload=payload,
        )
    )
    from app.core.redis import redis

    await redis().setex(
        f"device:{device.id}:heartbeat",
        settings.gateway_heartbeat_ttl_seconds,
        json.dumps({"received_at": received_at.isoformat()}),
    )
    await db.commit()
    await _publish_device_snapshot(db)
    if execution:
        await _publish_execution_task_update(db, execution)
    return {"ok": True, "device": _device_dict(device), "global_estop_active": estop_active, "execution_id": execution.gateway_execution_id if execution else None}


@router.post(
    "/gateway/{device_code}/calibration",
    summary="上报机器人定位校准结果",
    description=(
        "记录机器人自动或人工定位校准的真实结果。校准成功且包含位置时更新设备位置；"
        "漂移量达到配置阈值时生成定位告警。"
    ),
    response_description="返回校准记录接收结果和对应设备标识。",
)
async def report_gateway_calibration(
    device_code: Annotated[str, Path(description="已注册设备的唯一编码。")],
    req: Annotated[GatewayCalibrationReport, Body(description="机器人定位校准的实际执行结果。")],
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: str | None = Header(default=None, description="设备首次注册时获得的专属网关密钥。"),
) -> dict:
    """Record the outcome of a real QR/manual localization correction."""

    device = await _require_device_key(db, device_code, x_device_gateway_key)
    duplicate = await db.scalar(
        select(DeviceEvent).where(DeviceEvent.device_id == device.id, DeviceEvent.event_id == req.event_id)
    )
    if duplicate:
        return {"ok": True, "duplicate": True}
    if req.position is not None and req.success:
        device.position_x = req.position.x
        device.position_y = req.position.y
        device.position_z = req.position.z
    payload = req.model_dump(mode="json", exclude_none=True)
    db.add(
        DeviceEvent(
            time=_now(),
            device_id=device.id,
            event_type="calibration",
            event_id=req.event_id,
            received_at=_now(),
            payload=payload,
        )
    )
    if req.drift_meters is not None and req.drift_meters >= settings.localization_warning_drift_meters:
        db.add(
            Alert(
                device_id=device.id,
                level="critical" if req.drift_meters >= settings.localization_forced_calibration_drift_meters else "warning",
                category="localization_drift",
                message=f"Device {device.code} reported localization drift of {req.drift_meters:.3f}m.",
                payload={"event_id": req.event_id, "drift_meters": req.drift_meters, "source": req.source},
            )
        )
    await db.flush()
    return {"ok": True, "device_id": str(device.id)}


@router.post(
    "/{device_id}/calibrate",
    summary="请求机器人执行人工定位校准",
    description="为指定设备写入 reset_pose 命令。响应表示命令已进入持久化队列，不表示设备已经完成校准。",
    response_description="返回入队结果、设备 UUID、命令 UUID 和投递状态。",
)
async def request_manual_calibration(
    device_id: Annotated[uuid.UUID, Path(description="目标设备的 UUID。")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("device.command")),
) -> dict:
    """Queue a manual pose-reset request for a real gateway device."""

    device = await db.get(Device, device_id)
    if device is None or not device.gateway_enabled:
        raise HTTPException(status_code=404, detail="device was not found or is disabled")
    queued = await queue_command(
        db,
        device,
        "reset_pose",
        source="operator",
        priority=95,
        idempotency_key=f"manual-calibration:{device.id}:{uuid.uuid4()}",
        payload={"source": "manual", "frame_id": "map"},
    )
    return {"ok": True, "device_id": str(device.id), "command_id": str(queued.id), "delivery": "queued"}


@router.get(
    "/gateway/{device_code}/commands",
    summary="拉取待执行机器人命令",
    description=(
        "供设备网关轮询尚未确认的有效命令。命令在设备提交 ACK 前会被重复返回，"
        "设备应以 command_id 保证本地执行幂等。"
    ),
    response_description="返回设备编码、全局急停状态和待执行命令列表。",
)
async def pull_gateway_commands(
    device_code: Annotated[str, Path(description="已注册设备的唯一编码。")],
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: str | None = Header(default=None, description="设备首次注册时获得的专属网关密钥。"),
) -> dict:
    """Return every unacknowledged command; repeated delivery is intentional until ACK."""
    device = await _require_device_key(db, device_code, x_device_gateway_key)
    estop_active, estop_cycle = await _global_estop_state()
    if estop_active:
        await _ensure_global_estop_command(db, device, estop_cycle or "runtime")

    result = await db.execute(
        select(DeviceCommand)
        .where(
            DeviceCommand.device_id == device.id,
            DeviceCommand.status.in_(PENDING_COMMAND_STATUSES),
            or_(DeviceCommand.expires_at.is_(None), DeviceCommand.expires_at > _now()),
        )
        .order_by(DeviceCommand.priority.desc(), DeviceCommand.created_at)
    )
    commands = result.scalars().all()
    delivered_at = _now()
    for command in commands:
        if command.last_delivered_at is None or command.last_delivered_at <= delivered_at - timedelta(seconds=settings.gateway_command_delivery_timeout_seconds):
            command.status = "delivered"
            command.delivered_at = command.delivered_at or delivered_at
            command.last_delivered_at = delivered_at
            command.delivery_attempts += 1
            db.add(
                DeviceEvent(
                    time=_now(),
                    device_id=device.id,
                    event_type="command_delivered",
                    payload={"command_id": str(command.id), "command": command.command},
                )
            )
    return {
        "device_code": device.code,
        "global_estop_active": estop_active,
        "commands": [_command_dict(command) for command in commands],
    }


@router.post(
    "/gateway/{device_code}/commands/{command_id}/ack",
    summary="确认机器人命令执行结果",
    description=(
        "由设备网关提交命令成功或失败结果。完全相同的终态确认可幂等重试；"
        "同一命令提交不同终态结果会返回冲突。"
    ),
    response_description="返回确认处理结果、命令 UUID 和最终状态。",
)
async def acknowledge_gateway_command(
    device_code: Annotated[str, Path(description="已注册设备的唯一编码。")],
    command_id: Annotated[uuid.UUID, Path(description="待确认命令的 UUID。")],
    req: Annotated[GatewayCommandAck, Body(description="机器人对指定命令的最终执行确认。")],
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: str | None = Header(default=None, description="设备首次注册时获得的专属网关密钥。"),
) -> dict:
    """Record device execution outcome for an outbound command."""
    device = await _require_device_key(db, device_code, x_device_gateway_key)
    result = await db.execute(
        select(DeviceCommand).where(DeviceCommand.id == command_id, DeviceCommand.device_id == device.id)
    )
    command = result.scalar_one_or_none()
    if command is None:
        raise HTTPException(status_code=404, detail="command was not found for this device")

    acknowledgement = req.model_dump(mode="json", exclude_none=True)
    if command.status in {"acknowledged", "failed"}:
        if command.status == req.status and command.acknowledgement == acknowledgement:
            return {"ok": True, "duplicate": True, "command_id": str(command.id), "status": command.status}
        raise HTTPException(status_code=409, detail="command already has a different terminal acknowledgement")
    command.status = req.status
    command.acknowledged_at = _now()
    command.acknowledgement = acknowledgement
    db.add(
        DeviceEvent(
            time=_now(),
            device_id=device.id,
            event_type="command_ack",
            payload={"command_id": str(command.id), "command": command.command, **acknowledgement},
        )
    )
    return {"ok": True, "command_id": str(command.id), "status": command.status}


@router.get(
    "",
    summary="查询机器人设备列表",
    description="查询系统中已注册的设备，可按当前状态和设备类型同时筛选。",
    response_description="返回符合筛选条件的设备列表。",
)
async def list_devices(
    status_filter: str | None = Query(None, alias="status", description="设备状态编码；省略时不按状态筛选。"),
    type_filter: str | None = Query(None, alias="type", description="设备类型编码；省略时不按类型筛选。"),
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("read")),
) -> list[dict]:
    """List all devices with optional filters."""
    stmt = select(Device)
    if status_filter:
        stmt = stmt.where(Device.status == status_filter)
    if type_filter:
        stmt = stmt.where(Device.type == type_filter)
    result = await db.execute(stmt.order_by(Device.code))
    return [_device_dict(d) for d in result.scalars().all()]


@router.get(
    "/{device_id}",
    summary="查询机器人设备基本信息",
    description="按设备 UUID 查询注册信息、当前状态、位置、能力和最近心跳等基本信息。",
    response_description="返回指定设备的当前基本信息。",
)
async def get_device(
    device_id: Annotated[uuid.UUID, Path(description="目标设备的 UUID。")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("read")),
) -> dict:
    result = await db.execute(select(Device).where(Device.id == device_id))
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="device was not found")
    return _device_dict(d)


@router.get(
    "/{device_id}/detail",
    summary="查询机器人设备运行详情",
    description="查询指定时间范围内的真实遥测轨迹，并返回该设备的告警和任务执行历史。",
    response_description="返回设备信息、遥测轨迹、告警列表和任务执行记录。",
)
async def get_device_detail(
    device_id: Annotated[uuid.UUID, Path(description="目标设备的 UUID。")],
    hours: int = Query(24, ge=1, le=168, description="遥测轨迹回溯时长，单位为小时，范围 1 至 168。"),
    limit: int = Query(500, ge=1, le=2000, description="最多返回的遥测事件数量，范围 1 至 2000。"),
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("read")),
) -> dict:
    """Return auditable telemetry, alert, and mission history for one device."""

    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device was not found")
    since = _now() - timedelta(hours=hours)
    telemetry = await db.execute(
        select(DeviceEvent)
        .where(DeviceEvent.device_id == device.id, DeviceEvent.time >= since, DeviceEvent.event_type == "telemetry")
        .order_by(DeviceEvent.time.asc())
        .limit(limit)
    )
    alerts = await db.execute(
        select(Alert).where(Alert.device_id == device.id).order_by(Alert.created_at.desc()).limit(100)
    )
    executions = await db.execute(
        select(MissionExecution, Task)
        .join(Task, Task.id == MissionExecution.task_id)
        .where(MissionExecution.device_id == device.id)
        .order_by(MissionExecution.dispatched_at.desc())
        .limit(100)
    )
    return {
        "device": _device_dict(device),
        "trajectory": [
            {
                "time": event.time.isoformat(),
                "position": (event.payload or {}).get("position"),
                "status": (event.payload or {}).get("status"),
                "battery": (event.payload or {}).get("battery"),
            }
            for event in telemetry.scalars().all()
            if isinstance((event.payload or {}).get("position"), dict)
        ],
        "alerts": [
            {
                "id": str(alert.id), "level": alert.level, "category": alert.category,
                "message": alert.message, "status": alert.status,
                "created_at": alert.created_at.isoformat(),
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
            }
            for alert in alerts.scalars().all()
        ],
        "executions": [
            {
                "id": str(execution.id), "execution_id": execution.gateway_execution_id,
                "task_id": str(task.id), "task_code": task.code, "task_name": task.name,
                "state": execution.state, "progress": execution.progress,
                "failure_code": execution.failure_code,
                "dispatched_at": execution.dispatched_at.isoformat(),
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            }
            for execution, task in executions.all()
        ],
    }


class CommandRequest(BaseModel):
    command: Literal["pause", "resume", "estop", "reset", "release"] = Field(description="控制命令类型。")
    device_id: uuid.UUID | None = Field(default=None, description="兼容字段；提供时必须与 URL 路径中的设备 UUID 一致。")
    payload: dict[str, Any] = Field(default_factory=dict, description="随命令下发的扩展参数；具体字段由设备接入协议约定。")


class BatchCommandRequest(BaseModel):
    command: Literal["pause", "resume", "estop", "reset", "release"] = Field(description="批量下发的控制命令类型。")
    section_id: str | None = Field(default=None, description="施工区域编码筛选；省略时覆盖全部区域。")
    device_type: str | None = Field(default=None, description="设备类型编码筛选；省略时覆盖全部设备类型。")
    process_id: str | None = Field(default=None, description="工序编码筛选，仅选择声明支持该工序的设备。")
    payload: dict[str, Any] = Field(default_factory=dict, description="随命令下发给每台目标设备的扩展参数。")


@router.post(
    "/{device_id}/command",
    summary="向单台机器人下发控制命令",
    description=(
        "将控制命令写入指定设备的持久化命令队列，等待设备网关拉取并确认。"
        "响应表示入队成功，不表示机器人已经执行。"
    ),
    response_description="返回入队结果、目标设备、命令类型、命令 UUID 和投递状态。",
)
async def send_command(
    device_id: Annotated[uuid.UUID, Path(description="目标设备的 UUID。")],
    req: Annotated[CommandRequest, Body(description="向单台机器人下发的控制命令和扩展参数。")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("device.command")),
) -> dict:
    """Queue a control command for one real gateway device."""
    if req.device_id is not None and req.device_id != device_id:
        raise HTTPException(status_code=422, detail="request device_id does not match the URL")
    device_result = await db.execute(select(Device).where(Device.id == device_id))
    device = device_result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="device was not found")

    estop_active, _ = await _global_estop_state()
    if estop_active and req.command in {"reset", "resume", "release"}:
        raise HTTPException(
            status_code=409,
            detail="global emergency stop is active; recover it before resuming a device",
        )
    queued_command = await queue_command(db, device, req.command, payload=req.payload, source="operator", priority=90)
    return {
        "ok": True,
        "device_id": str(device_id),
        "command": req.command,
        "command_id": str(queued_command.id),
        "delivery": "queued",
    }


@router.post(
    "/commands/batch",
    summary="向机器人设备组批量下发命令",
    description=(
        "按施工区域、设备类型和支持工序的交集筛选已启用设备，并为每台设备创建独立的持久化命令。"
        "响应表示命令已入队，不表示设备已经执行。"
    ),
    response_description="返回所有目标设备编码及其对应的命令 UUID。",
)
async def send_batch_command(
    req: Annotated[BatchCommandRequest, Body(description="批量控制命令、设备筛选条件和扩展参数。")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("device.command")),
) -> dict:
    """Address a fleet group using persisted device tags, with one ACK per target."""
    statement = select(Device).where(Device.gateway_enabled == True)
    if req.section_id:
        statement = statement.where(Device.section_id == req.section_id)
    if req.device_type:
        statement = statement.where(Device.type == req.device_type)
    devices = (await db.execute(statement)).scalars().all()
    selected = [
        device for device in devices
        if not req.process_id or req.process_id in (device.capabilities or {}).get("processes", [])
    ]
    queued = [
        await queue_command(db, device, req.command, payload=req.payload, source="operator", priority=90)
        for device in selected
    ]
    return {"ok": True, "targets": [device.code for device in selected], "command_ids": [str(command.id) for command in queued]}


async def _publish_execution_task_update(db: AsyncSession, execution: MissionExecution) -> None:
    task = await db.get(Task, execution.task_id)
    if task is None:
        return
    from app.core.redis import CHANNEL_TASKS, redis

    payload = {
        "id": str(task.id), "code": task.code, "name": task.name, "process_id": task.process_id,
        "device_id": str(task.device_id) if task.device_id else None, "status": task.status,
        "priority": task.priority, "map_point_id": str(task.map_point_id) if task.map_point_id else None,
        "progress": task.progress, "dependencies": task.dependencies or [], "estimated_duration": task.estimated_duration,
        "planned_start": task.planned_start.isoformat() if task.planned_start else None,
        "planned_end": task.planned_end.isoformat() if task.planned_end else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "deliverable_qty": task.deliverable_qty, "deliverable_unit": task.deliverable_unit,
        "completed_qty": task.completed_qty, "stage": task.stage, "params": task.params or {},
    }
    await redis().publish(CHANNEL_TASKS, json.dumps({"channel": CHANNEL_TASKS, "data": {"type": "task_updated", **payload}}))


def _device_dict(d: Device) -> dict:
    return {
        "id": str(d.id),
        "code": d.code,
        "name": d.name,
        "type": d.type,
        "model": d.model,
        "status": d.status,
        "battery": d.battery,
        "position": {"x": d.position_x, "y": d.position_y, "z": d.position_z},
        "section_id": d.section_id,
        "capabilities": d.capabilities,
        "health": d.health,
        "operational_metrics": d.operational_metrics or {},
        "current_task": (d.operational_metrics or {}).get("current_task"),
        "task_progress": (d.operational_metrics or {}).get("task_progress"),
        "last_heartbeat": d.last_heartbeat.isoformat() if d.last_heartbeat else None,
    }
