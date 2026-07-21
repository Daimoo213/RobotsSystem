"""SQLAlchemy ORM models for all relation tables.

所有数据通过外键关联，派生指标实时计算，不存储冗余字段。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Users ────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16))  # pm / om
    display_name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ── Devices ──────────────────────────────────────────────
class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(32), index=True)  # agv/excavator/crane/masonry/inspect
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capabilities: Mapped[dict] = mapped_column(JSONB, default=dict)
    section_tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict)

    status: Mapped[str] = mapped_column(String(16), default="idle", index=True)
    battery: Mapped[float] = mapped_column(Float, default=100.0)
    position_x: Mapped[float] = mapped_column(Float, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, default=0.0)
    position_z: Mapped[float] = mapped_column(Float, default=0.0)
    section_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # 体检指标: connection / location / battery / task / safety
    health: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Latest measured operational values. The immutable telemetry history is
    # retained in DeviceEvent; this field only accelerates dashboard queries.
    operational_metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    gateway_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    gateway_key_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    gateway_key_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关联
    events: Mapped[list["DeviceEvent"]] = relationship(back_populates="device", lazy="dynamic")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="device", lazy="dynamic")
    tasks: Mapped[list["Task"]] = relationship(back_populates="device", lazy="dynamic")


# ── Tasks ────────────────────────────────────────────────
class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    process_id: Mapped[str] = mapped_column(String(32), index=True)  # 29项工序ID
    script_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scripts.id"), nullable=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True
    )
    # 外键关联到 map_points（替代原来的 target_point_id 字符串）
    map_point_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("map_points.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    dependencies: Mapped[list] = mapped_column(JSONB, default=list)  # task ids
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    estimated_duration: Mapped[int] = mapped_column(Integer, default=60)  # 预估工期(分钟)
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    planned_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 交付结果量化
    deliverable_qty: Mapped[float | None] = mapped_column(Float, nullable=True)  # 计划交付量
    deliverable_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    completed_qty: Mapped[float] = mapped_column(Float, default=0.0)  # 已完成量（随进度更新）

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    stage: Mapped[str] = mapped_column(String(32), default="earthwork")

    # 关联
    device = relationship("Device", back_populates="tasks", lazy="selectin")
    map_point = relationship("MapPoint", lazy="selectin")


# ── Scripts (stage configs) ──────────────────────────────
class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ── Alerts ───────────────────────────────────────────────
class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True
    )
    level: Mapped[str] = mapped_column(String(16), index=True)  # critical/warning/info
    category: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    device = relationship("Device", back_populates="alerts")


# ── Map ──────────────────────────────────────────────────
class MapRegion(Base):
    __tablename__ = "map_regions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    region_type: Mapped[str] = mapped_column(String(32))  # work/restricted/stack/parking
    polygon: Mapped[list] = mapped_column(JSONB, default=list)  # [[x,y],...]
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MapPoint(Base):
    __tablename__ = "map_points"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    point_type: Mapped[str] = mapped_column(String(32))  # pit/material/exit/charge/...
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    z: Mapped[float] = mapped_column(Float, default=0.0)
    process_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device_types: Mapped[list] = mapped_column(JSONB, default=list)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    qrcode_id: Mapped[str | None] = mapped_column(String(96), nullable=True, unique=True)
    qrcode_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 关联
    tasks: Mapped[list["Task"]] = relationship(back_populates="map_point", lazy="dynamic")


# ── Cameras ──────────────────────────────────────────────
class Camera(Base):
    """摄像头设备。"""
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # CAM-01
    name: Mapped[str] = mapped_column(String(64))  # 东南角基坑摄像头
    location: Mapped[str] = mapped_column(String(128))  # 东南角基坑作业面
    stream_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    position_x: Mapped[float] = mapped_column(Float, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, default=0.0)
    is_online: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    detections: Mapped[list["CameraDetection"]] = relationship(
        back_populates="camera", lazy="dynamic", cascade="all, delete-orphan"
    )


class CameraDetection(Base):
    """摄像头AI识别记录。每次识别写入一条记录，前端查询最新记录。

    模拟写入：runtime 定期生成模拟识别数据写入此表。
    """
    __tablename__ = "camera_detections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id"), nullable=False, index=True
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    # 识别结果
    excavator_count: Mapped[int] = mapped_column(Integer, default=0)  # 挖机数
    truck_count: Mapped[int] = mapped_column(Integer, default=0)  # 渣土车数
    person_count: Mapped[int] = mapped_column(Integer, default=0)  # 人员数
    dust_level: Mapped[str] = mapped_column(String(16), default="良")  # 扬尘等级: 优/良/中/差
    slope_risk: Mapped[str] = mapped_column(String(16), default="稳定")  # 边坡风险: 稳定/关注/危险
    ai_compliance_rate: Mapped[float] = mapped_column(Float, default=100.0)  # AI合规率

    camera = relationship("Camera", back_populates="detections")


# ── Device Events (时序事件流) ───────────────────────────
class DeviceEvent(Base):
    """Time-series event log. 环境数据（扬尘等）也从这里聚合提取。"""

    __tablename__ = "device_events"
    __table_args__ = (
        UniqueConstraint("device_id", "event_id", name="uq_device_events_device_event_id"),
    )

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, default=_now
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), primary_key=True
    )
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    boot_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    # telemetry / status_change / task_event / alert / environment
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    # environment 类型的 payload 包含: { "dust_level": "良", "temperature": 28.5, ... }

    device = relationship("Device", back_populates="events")


class DeviceCommand(Base):
    """Persisted command queue consumed by HTTP device gateways."""

    __tablename__ = "device_commands"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True
    )
    command: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    source: Mapped[str] = mapped_column(String(32), default="system")
    priority: Mapped[int] = mapped_column(Integer, default=50)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mission_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mission_executions.id"), nullable=True, index=True
    )
    # pending -> delivered -> acknowledged / failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledgement: Mapped[dict] = mapped_column(JSONB, default=dict)


class Project(Base):
    """Single active construction project configured explicitly during first-run setup."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    map_frame: Mapped[str] = mapped_column(String(64), default="map")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Hong_Kong")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MissionExecution(Base):
    """A durable execution attempt that connects a task to one physical device.

    Stable states: dispatched, accepted, running, paused, completed, failed,
    cancelled. Transitional operator intents: pause_requested,
    resume_requested, and cancel_requested. A transition is finalized only by
    subsequent gateway telemetry, never by a browser request or command ACK.
    """

    __tablename__ = "mission_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False, index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True
    )
    gateway_execution_id: Mapped[str] = mapped_column(String(96), unique=True)
    state: Mapped[str] = mapped_column(String(24), default="dispatched", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    completed_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class SafetyState(Base):
    """Durable global safety latch. Redis is only a notification transport."""

    __tablename__ = "safety_states"

    scope: Mapped[str] = mapped_column(String(32), primary_key=True, default="global")
    active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    cycle_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class PointCloudSnapshot(Base):
    """A real map/point-cloud snapshot supplied by an external mapping gateway."""

    __tablename__ = "pointcloud_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(96), unique=True)
    source_id: Mapped[str] = mapped_column(String(96), index=True)
    frame_id: Mapped[str] = mapped_column(String(64), default="map")
    points: Mapped[list] = mapped_column(JSONB, default=list)
    # ``metadata`` is reserved by SQLAlchemy declarative models. Keep the
    # persisted column/API name while using a non-reserved Python attribute.
    snapshot_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class MapAsset(Base):
    """Versioned external mesh or occupancy-map asset registered by a mapping gateway."""

    __tablename__ = "map_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(96), unique=True)
    source_id: Mapped[str] = mapped_column(String(96), index=True)
    asset_type: Mapped[str] = mapped_column(String(32), index=True)  # mesh_gltf / octomap / geojson
    asset_uri: Mapped[str] = mapped_column(String(1024))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frame_id: Mapped[str] = mapped_column(String(64), default="map")
    asset_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class MaintenanceWorkOrder(Base):
    """A real maintenance reminder derived from reported runtime or mileage."""

    __tablename__ = "maintenance_work_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False, index=True
    )
    trigger_type: Mapped[str] = mapped_column(String(32), index=True)  # runtime_hours / mileage_km
    threshold: Mapped[float] = mapped_column(Float)
    observed_value: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
