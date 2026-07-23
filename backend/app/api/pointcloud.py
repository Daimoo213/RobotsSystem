"""Persistent point-cloud snapshots from external SLAM or Gazebo bridges."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.devices import require_gateway_api_key
from app.core.database import get_db
from app.core.redis import CHANNEL_POINTCLOUD, redis
from app.core.security import require
from app.models.models import PointCloudSnapshot

router = APIRouter(prefix="/pointcloud", tags=["pointcloud"])
MAX_POINTS_PER_SNAPSHOT = 50_000


class PointCloudSnapshotIn(BaseModel):
    event_id: str = Field(description="上游点云源生成的幂等事件标识；重复提交同一标识不会重复入库", min_length=1, max_length=96)
    source_id: str = Field(description="产生点云的机器人、传感器、SLAM 节点或 Gazebo 桥接器标识", min_length=1, max_length=96)
    frame_id: str = Field(description="点坐标使用的坐标系标识", default="map", min_length=1, max_length=64)
    observed_at: datetime = Field(description="点云快照的采集时间，使用带时区的 ISO 8601 时间")
    points: list[list[float]] = Field(description=f"点云坐标数组，每个点必须为 [x, y, z]，单次最多 {MAX_POINTS_PER_SNAPSHOT} 个点", min_length=1, max_length=MAX_POINTS_PER_SNAPSHOT)
    metadata: dict = Field(description="点云源附带的扩展元数据，字段由设备接入协议约定", default_factory=dict)

    @field_validator("points")
    @classmethod
    def validate_points(cls, points: list[list[float]]) -> list[list[float]]:
        if any(len(point) != 3 for point in points):
            raise ValueError("each point must be [x, y, z]")
        return points


def _snapshot_dict(snapshot: PointCloudSnapshot) -> dict:
    return {
        "id": str(snapshot.id), "event_id": snapshot.event_id, "source_id": snapshot.source_id,
        "frame_id": snapshot.frame_id, "points": snapshot.points,
        "total_count": len(snapshot.points), "progress": 1.0, "metadata": snapshot.snapshot_metadata,
        "observed_at": snapshot.observed_at.isoformat(), "received_at": snapshot.received_at.isoformat(),
    }


@router.post(
    "/gateway/snapshots",
    summary="上传点云快照",
    description="供机器人、SLAM 节点或 Gazebo 桥接器上传一帧真实点云。接口按事件标识幂等，成功入库后通过实时通道发布该快照；调用时必须提供有效的设备网关 API 密钥。",
    response_description="点云快照接收结果；重复事件会返回已有快照标识",
    openapi_extra={"requestBody": {"description": "外部点云源采集的一帧三维点云快照"}},
)
async def ingest_snapshot(
    req: Annotated[PointCloudSnapshotIn, Body(description="外部点云源采集的一帧三维点云快照")],
    db: AsyncSession = Depends(get_db),
    _gateway: None = Depends(require_gateway_api_key),
) -> dict:
    existing = await db.scalar(select(PointCloudSnapshot).where(PointCloudSnapshot.event_id == req.event_id))
    if existing:
        return {"ok": True, "duplicate": True, "snapshot_id": str(existing.id)}
    snapshot = PointCloudSnapshot(
        **req.model_dump(exclude={"metadata"}),
        snapshot_metadata=req.metadata,
    )
    db.add(snapshot)
    await db.flush()
    payload = _snapshot_dict(snapshot)
    await redis().publish(CHANNEL_POINTCLOUD, json.dumps({"channel": CHANNEL_POINTCLOUD, "data": payload}, default=str))
    return {"ok": True, "snapshot_id": str(snapshot.id), "points_count": len(snapshot.points)}


@router.get(
    "/latest",
    summary="获取最新点云快照",
    description="按采集时间查询数据库中最新的一帧点云快照；尚无真实点云数据时返回 has_data=false。调用方需要具备读取权限。",
    response_description="最新点云快照，或明确的无数据状态",
)
async def latest_snapshot(db: AsyncSession = Depends(get_db), _role=Depends(require("read"))) -> dict:
    snapshot = await db.scalar(select(PointCloudSnapshot).order_by(PointCloudSnapshot.observed_at.desc()).limit(1))
    if snapshot is None:
        return {"has_data": False, "points": [], "total_count": 0, "progress": 0.0}
    return {"has_data": True, **_snapshot_dict(snapshot)}


@router.get(
    "/status",
    summary="获取点云数据状态",
    description="返回最新点云来源、是否已有数据、点数和更新时间，不生成或补充任何模拟点云。调用方需要具备读取权限。",
    response_description="当前点云数据源和最新快照状态",
)
async def status(db: AsyncSession = Depends(get_db), _role=Depends(require("read"))) -> dict:
    snapshot = await db.scalar(select(PointCloudSnapshot).order_by(PointCloudSnapshot.observed_at.desc()).limit(1))
    return {
        "source": snapshot.source_id if snapshot else "not_configured",
        "active": snapshot is not None,
        "points_count": len(snapshot.points) if snapshot else 0,
        "progress": 1.0 if snapshot else 0.0,
        "updated_at": snapshot.observed_at.isoformat() if snapshot else None,
    }
