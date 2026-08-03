"""Complete point-cloud map ingestion owned by an external mapping gateway."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.devices import require_gateway_api_key
from app.core.coordinates import MAP_FRAME_CONVENTION, ensure_map_frame
from app.core.database import get_db
from app.core.redis import CHANNEL_POINTCLOUD, redis
from app.core.security import require
from app.models.models import PointCloudMap, Project

router = APIRouter(prefix="/pointcloud", tags=["pointcloud"])


class PointCloudMapIn(BaseModel):
    """A complete, already fused and sampled map from the mapping pipeline."""

    model_config = ConfigDict(extra="forbid")

    map_id: str = Field(
        description="完整点云地图版本的稳定唯一标识；重复提交相同标识不会重复写入",
        min_length=1,
        max_length=96,
    )
    source_id: str = Field(
        description="生成完整地图的机器人、传感器、SLAM 节点或仿真桥接器标识",
        min_length=1,
        max_length=96,
    )
    frame_id: str = Field(
        description=f"点坐标使用的项目地图坐标系标识，必须与项目配置一致。{MAP_FRAME_CONVENTION}",
        default="map",
        min_length=1,
        max_length=64,
    )
    observed_at: datetime = Field(description="完整地图的采集或生成时间，使用带时区的 ISO 8601 时间")
    points: list[list[float]] = Field(
        description="完整点云地图坐标数组；每个点固定为 [x, y, z]，其中 X/Y 位于水平面，+Z 竖直向上。点云必须在上传前由建图端完成融合和抽样",
        min_length=1,
    )
    metadata: dict = Field(description="建图端附带的真实地图元数据", default_factory=dict)

    @field_validator("points")
    @classmethod
    def validate_points(cls, points: list[list[float]]) -> list[list[float]]:
        for point in points:
            if len(point) != 3:
                raise ValueError("每个点必须是 [x, y, z] 三元坐标")
            if any(not math.isfinite(value) for value in point):
                raise ValueError("点云坐标必须是有限数字")
        return points


def _active_project(db: AsyncSession) -> object:
    return select(Project).where(Project.is_active.is_(True)).order_by(Project.created_at.desc()).limit(1)


def _map_dict(pointcloud_map: PointCloudMap) -> dict:
    return {
        "map_id": pointcloud_map.map_id,
        "source_id": pointcloud_map.source_id,
        "frame_id": pointcloud_map.frame_id,
        "points": pointcloud_map.points,
        "total_count": len(pointcloud_map.points),
        "progress": 1.0,
        "metadata": pointcloud_map.map_metadata,
        "observed_at": pointcloud_map.observed_at.isoformat(),
        "received_at": pointcloud_map.received_at.isoformat(),
    }


async def _mapping_enabled(db: AsyncSession) -> bool:
    project = await db.scalar(_active_project(db))
    return bool(project and project.mapping_enabled)


@router.post(
    "/gateway/map",
    summary="上传完整点云地图",
    description=(
        "供外部建图网关上传一份已经完成融合和抽样的完整点云地图。"
        "平台只保存当前地图，新的 map_id 会原子替换旧地图；相同 map_id 幂等返回。"
        "上传前必须由 O&M 开启建图模式，并提供有效的设备网关 API 密钥。"
    ),
    response_description="完整点云地图接收结果和当前地图标识",
)
async def ingest_map(
    req: Annotated[PointCloudMapIn, Body(description="外部建图端生成的完整三维点云地图")],
    db: AsyncSession = Depends(get_db),
    _gateway: None = Depends(require_gateway_api_key),
) -> dict:
    project = await db.scalar(_active_project(db))
    if project is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目尚未初始化，不能上传点云地图")
    if not project.mapping_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="建图模式未开启，点云地图上传已被关闭")
    ensure_map_frame(req.frame_id, project.map_frame)

    current = await db.scalar(
        select(PointCloudMap).where(PointCloudMap.scope == "current").with_for_update()
    )
    if current is not None and current.map_id == req.map_id:
        return {"ok": True, "duplicate": True, "map_id": current.map_id, "points_count": len(current.points)}

    values = req.model_dump(exclude={"metadata"})
    if current is None:
        current = PointCloudMap(scope="current", **values, map_metadata=req.metadata)
        db.add(current)
    else:
        current.map_id = values["map_id"]
        current.source_id = values["source_id"]
        current.frame_id = values["frame_id"]
        current.observed_at = values["observed_at"]
        current.received_at = datetime.now(timezone.utc)
        current.points = values["points"]
        current.map_metadata = req.metadata

    await db.flush()
    payload = _map_dict(current)
    await redis().publish(CHANNEL_POINTCLOUD, json.dumps({"channel": CHANNEL_POINTCLOUD, "data": payload}, default=str))
    return {"ok": True, "replaced": True, "map_id": current.map_id, "points_count": len(current.points)}


@router.get(
    "/map",
    summary="获取当前完整点云地图",
    description="读取数据库中当前唯一的完整点云地图。接口不会融合、抽样或生成点云；尚无真实地图时返回 has_data=false。",
    response_description="当前完整点云地图，或明确的无数据状态",
)
async def current_map(db: AsyncSession = Depends(get_db), _role=Depends(require("read"))) -> dict:
    pointcloud_map = await db.scalar(select(PointCloudMap).where(PointCloudMap.scope == "current"))
    if pointcloud_map is None:
        return {"has_data": False, "mapping_enabled": await _mapping_enabled(db), "points": [], "total_count": 0, "progress": 0.0}
    return {"has_data": True, "mapping_enabled": await _mapping_enabled(db), **_map_dict(pointcloud_map)}


@router.get(
    "/status",
    summary="获取完整点云地图状态",
    description="返回建图模式开关、当前完整地图来源、点数和更新时间，不生成或补充任何点云。",
    response_description="当前点云地图和建图模式状态",
)
async def status(db: AsyncSession = Depends(get_db), _role=Depends(require("read"))) -> dict:
    pointcloud_map = await db.scalar(select(PointCloudMap).where(PointCloudMap.scope == "current"))
    return {
        "mapping_enabled": await _mapping_enabled(db),
        "source": pointcloud_map.source_id if pointcloud_map else None,
        "map_id": pointcloud_map.map_id if pointcloud_map else None,
        "active": pointcloud_map is not None,
        "points_count": len(pointcloud_map.points) if pointcloud_map else 0,
        "progress": 1.0 if pointcloud_map else 0.0,
        "updated_at": pointcloud_map.observed_at.isoformat() if pointcloud_map else None,
    }
