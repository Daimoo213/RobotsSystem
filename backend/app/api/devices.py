"""Devices router — list / detail / command."""

from __future__ import annotations

import json
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
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
    x_device_gateway_key: str | None = Header(default=None),
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
    x: float
    y: float
    z: float = 0.0


class GatewayRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=32)
    model: str | None = Field(default=None, max_length=64)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    section_tags: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, Any] = Field(default_factory=dict)
    section_id: str | None = Field(default=None, max_length=32)
    health: dict[str, Any] = Field(default_factory=dict)
    protocol_version: str = Field(default="v1", max_length=32)


class GatewayMissionUpdate(BaseModel):
    execution_id: str = Field(min_length=1, max_length=96)
    state: Literal["accepted", "running", "paused", "completed", "failed", "cancelled"]
    progress: float | None = Field(default=None, ge=0, le=100)
    completed_qty: float | None = Field(default=None, ge=0)
    result: dict[str, Any] | None = None
    failure_code: str | None = Field(default=None, max_length=96)
    estimated_completion_at: datetime | None = None


class GatewayOperationalMetrics(BaseModel):
    """Measurements reported by a physical robot or external bridge.

    Values are intentionally optional: device vendors expose different sensor
    sets. Omitted values are never estimated by the control plane.
    """

    power_kw: float | None = Field(default=None, ge=0)
    energy_kwh_total: float | None = Field(default=None, ge=0)
    mileage_km_total: float | None = Field(default=None, ge=0)
    runtime_hours_total: float | None = Field(default=None, ge=0)
    payload_ratio: float | None = Field(default=None, ge=0, le=1)
    localization_drift_meters: float | None = Field(default=None, ge=0)


class GatewayTelemetry(BaseModel):
    """Gateway-neutral telemetry. Additional vendor metrics are retained in the event payload."""

    model_config = ConfigDict(extra="allow")

    event_id: str = Field(min_length=1, max_length=96)
    boot_id: str = Field(min_length=1, max_length=96)
    sequence: int = Field(ge=0)
    frame_id: str = Field(default="map", min_length=1, max_length=64)
    schema_version: str = Field(default="v1", min_length=1, max_length=32)
    status: str | None = Field(default=None, min_length=1, max_length=16)
    battery: float | None = Field(default=None, ge=0, le=100)
    position: GatewayPosition | None = None
    section_id: str | None = Field(default=None, max_length=32)
    health: dict[str, Any] | None = None
    metrics: GatewayOperationalMetrics | None = None
    observed_at: datetime | None = None
    mission: GatewayMissionUpdate | None = None


class GatewayCommandAck(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["acknowledged", "failed"]
    message: str | None = Field(default=None, max_length=512)


class GatewayCalibrationReport(BaseModel):
    event_id: str = Field(min_length=1, max_length=96)
    qrcode_id: str | None = Field(default=None, max_length=96)
    source: Literal["automatic", "manual"]
    observed_at: datetime
    success: bool
    position: GatewayPosition | None = None
    drift_meters: float | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=512)


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


@router.post("/gateway/register")
async def register_gateway_device(
    req: GatewayRegistration,
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: str | None = Header(default=None),
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


@router.post("/gateway/{device_code}/telemetry")
async def report_gateway_telemetry(
    device_code: str,
    req: GatewayTelemetry,
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: str | None = Header(default=None),
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


@router.post("/gateway/{device_code}/calibration")
async def report_gateway_calibration(
    device_code: str,
    req: GatewayCalibrationReport,
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: str | None = Header(default=None),
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


@router.post("/{device_id}/calibrate")
async def request_manual_calibration(
    device_id: uuid.UUID,
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


@router.get("/gateway/{device_code}/commands")
async def pull_gateway_commands(
    device_code: str,
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: str | None = Header(default=None),
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


@router.post("/gateway/{device_code}/commands/{command_id}/ack")
async def acknowledge_gateway_command(
    device_code: str,
    command_id: uuid.UUID,
    req: GatewayCommandAck,
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: str | None = Header(default=None),
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


@router.get("")
async def list_devices(
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
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


@router.get("/{device_id}")
async def get_device(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("read")),
) -> dict:
    result = await db.execute(select(Device).where(Device.id == device_id))
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="device was not found")
    return _device_dict(d)


@router.get("/{device_id}/detail")
async def get_device_detail(
    device_id: uuid.UUID,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(500, ge=1, le=2000),
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
    command: Literal["pause", "resume", "estop", "reset", "release"]
    device_id: uuid.UUID | None = None  # None = all devices
    payload: dict[str, Any] = Field(default_factory=dict)


class BatchCommandRequest(BaseModel):
    command: Literal["pause", "resume", "estop", "reset", "release"]
    section_id: str | None = None
    device_type: str | None = None
    process_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/{device_id}/command")
async def send_command(
    device_id: uuid.UUID,
    req: CommandRequest,
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


@router.post("/commands/batch")
async def send_batch_command(
    req: BatchCommandRequest,
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
