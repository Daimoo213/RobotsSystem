"""Project map regions and points persisted by authorized operators or import jobs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.devices import require_gateway_api_key
from app.core.database import get_db
from app.core.security import require
from app.models.models import MapAsset, MapPoint, MapRegion, Task

router = APIRouter(prefix="/map", tags=["map"])
DEFAULT_MAP_COLOR = "#2FD7FF"


def _publish_map_change(change_type: str, data: dict) -> None:
    """Schedule map refresh notifications without making persistence depend on Redis."""

    async def publish() -> None:
        try:
            import json

            from app.core.redis import CHANNEL_EVENTS, redis

            await redis().publish(
                CHANNEL_EVENTS,
                json.dumps({"channel": CHANNEL_EVENTS, "data": {"type": change_type, **data}}, default=str),
            )
        except Exception:
            return

    import asyncio

    asyncio.create_task(publish())


def _validate_asset_uri(asset_uri: str) -> None:
    """Only accept absolute HTTPS or configured object-store URI references."""

    parsed = urlparse(asset_uri)
    if parsed.scheme == "https" and parsed.netloc:
        return
    if parsed.scheme in {"s3", "gs", "oss"} and parsed.netloc:
        return
    raise ValueError("asset_uri must be an absolute https, s3, gs, or oss URI")


def _validate_polygon(polygon: list[list[float]]) -> None:
    if len(polygon) < 3 or any(len(point) != 2 for point in polygon):
        raise ValueError("polygon must contain at least three [x, y] vertices")
    area = 0.0
    for index, point in enumerate(polygon):
        next_point = polygon[(index + 1) % len(polygon)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    if abs(area) < 1e-6:
        raise ValueError("polygon area must be non-zero")


class MapRegionInput(BaseModel):
    code: str = Field(description="区域唯一业务编码，同一项目内不可重复", min_length=1, max_length=32)
    name: str = Field(description="区域显示名称", min_length=1, max_length=64)
    region_type: str = Field(description="区域类型，由项目按业务场景约定，如作业区或禁行区", min_length=1, max_length=32)
    polygon: list[list[float]] = Field(description="区域边界顶点，使用地图坐标系下的 [x, y] 坐标，至少三个点且围成的面积非零")
    stage: str | None = Field(description="区域所属施工阶段或业务阶段；不分阶段时留空", default=None, max_length=32)
    color: str = Field(description="区域在地图栅格上显示的六位十六进制边线颜色", default=DEFAULT_MAP_COLOR, pattern=r"^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def validate_geometry(self) -> "MapRegionInput":
        _validate_polygon(self.polygon)
        return self


class MapPointInput(BaseModel):
    code: str = Field(description="点位唯一业务编码，同一项目内不可重复", min_length=1, max_length=32)
    name: str = Field(description="点位显示名称", min_length=1, max_length=64)
    point_type: str = Field(description="点位类型，由项目按业务场景约定，如装载点、卸载点或充电点", min_length=1, max_length=32)
    x: float = Field(description="点位在地图坐标系中的 X 坐标")
    y: float = Field(description="点位在地图坐标系中的 Y 坐标")
    z: float = Field(description="点位在地图坐标系中的 Z 坐标", default=0.0)
    process_type: str | None = Field(description="点位关联的作业流程类型；无固定流程时留空", default=None, max_length=32)
    device_types: list[str] = Field(description="允许或适合在该点位作业的设备类型编码列表", default_factory=list)
    stage: str | None = Field(description="点位所属施工阶段或业务阶段；不分阶段时留空", default=None, max_length=32)
    qrcode_id: str | None = Field(description="现场二维码或视觉标记的唯一标识；未配置标记时留空", default=None, min_length=1, max_length=96)
    qrcode_type: str | None = Field(description="二维码或视觉标记类型；未配置标记时留空", default=None, max_length=32)
    color: str = Field(description="点位在地图栅格上显示的六位十六进制边线颜色", default=DEFAULT_MAP_COLOR, pattern=r"^#[0-9a-fA-F]{6}$")


class MapAssetIn(BaseModel):
    """Reference to a map product owned by the external mapping pipeline."""

    event_id: str = Field(description="上游映射流水线生成的幂等事件标识；重复提交同一标识不会重复入库", min_length=1, max_length=96)
    source_id: str = Field(description="生成地图资产的机器人、仿真桥接器或映射任务标识", min_length=1, max_length=96)
    asset_type: Literal["mesh_gltf", "octomap", "geojson"] = Field(description="地图资产格式：GLTF 网格、OctoMap 占据地图或 GeoJSON 地理数据")
    asset_uri: str = Field(description="资产文件的绝对访问地址，仅接受 HTTPS 或 s3、gs、oss 对象存储 URI", min_length=1, max_length=1024)
    checksum_sha256: str | None = Field(description="资产文件的 SHA-256 校验值，使用 64 位十六进制字符串；未提供校验值时留空", default=None, pattern=r"^[0-9a-fA-F]{64}$")
    frame_id: str = Field(description="资产使用的坐标系标识", default="map", min_length=1, max_length=64)
    metadata: dict = Field(description="上游系统附带的扩展元数据，字段由设备集成协议约定", default_factory=dict)
    observed_at: datetime = Field(description="上游系统生成或观测到该资产的时间，使用带时区的 ISO 8601 时间")

    @model_validator(mode="after")
    def validate_asset_reference(self) -> "MapAssetIn":
        _validate_asset_uri(self.asset_uri)
        return self


def _region_dict(region: MapRegion) -> dict:
    return {"id": str(region.id), "code": region.code, "name": region.name, "region_type": region.region_type, "polygon": region.polygon, "stage": region.stage, "color": region.color}


def _point_dict(point: MapPoint) -> dict:
    return {"id": str(point.id), "code": point.code, "name": point.name, "point_type": point.point_type, "x": point.x, "y": point.y, "z": point.z, "process_type": point.process_type, "device_types": point.device_types, "stage": point.stage, "qrcode_id": point.qrcode_id, "qrcode_type": point.qrcode_type, "color": point.color}


def _asset_dict(asset: MapAsset) -> dict:
    return {
        "id": str(asset.id), "event_id": asset.event_id, "source_id": asset.source_id,
        "asset_type": asset.asset_type, "asset_uri": asset.asset_uri,
        "checksum_sha256": asset.checksum_sha256, "frame_id": asset.frame_id,
        "metadata": asset.asset_metadata or {}, "observed_at": asset.observed_at.isoformat(),
        "received_at": asset.received_at.isoformat(),
    }


@router.get(
    "/regions",
    summary="查询地图区域",
    description="按区域编码排序返回当前项目中已持久化的全部地图区域。调用方需要具备地图读取权限。",
    response_description="地图区域列表",
)
async def list_regions(db: AsyncSession = Depends(get_db), _role=Depends(require("map.read"))) -> list[dict]:
    return [_region_dict(region) for region in (await db.execute(select(MapRegion).order_by(MapRegion.code))).scalars().all()]


@router.post(
    "/regions",
    summary="创建地图区域",
    description="创建一个由地图坐标多边形定义的业务区域。区域编码必须唯一，调用方需要具备地图管理权限。",
    response_description="创建成功后的地图区域",
    openapi_extra={"requestBody": {"description": "待创建的地图区域参数"}},
)
async def create_region(
    req: Annotated[MapRegionInput, Body(description="待创建的地图区域参数")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.manage")),
) -> dict:
    existing = await db.scalar(select(MapRegion).where(MapRegion.code == req.code))
    if existing:
        raise HTTPException(status_code=409, detail="map region code already exists")
    region = MapRegion(**req.model_dump())
    db.add(region)
    await db.flush()
    response = _region_dict(region)
    _publish_map_change("map_region_created", response)
    return response


@router.put(
    "/regions/{region_id}",
    summary="更新地图区域",
    description="使用完整区域参数替换指定地图区域的业务属性和边界。调用方需要具备地图管理权限。",
    response_description="更新后的地图区域",
    openapi_extra={"requestBody": {"description": "地图区域的完整更新参数"}},
)
async def update_region(
    region_id: Annotated[uuid.UUID, Path(description="待更新地图区域的 UUID")],
    req: Annotated[MapRegionInput, Body(description="地图区域的完整更新参数")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.manage")),
) -> dict:
    region = await db.get(MapRegion, region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="map region not found")
    for field, value in req.model_dump().items():
        setattr(region, field, value)
    await db.flush()
    response = _region_dict(region)
    _publish_map_change("map_region_updated", response)
    return response


@router.delete(
    "/regions/{region_id}",
    summary="删除地图区域",
    description="永久删除指定地图区域并发布地图变更事件。调用方需要具备地图管理权限。",
    response_description="删除结果及已删除的区域 UUID",
)
async def delete_region(
    region_id: Annotated[uuid.UUID, Path(description="待删除地图区域的 UUID")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.manage")),
) -> dict:
    region = await db.get(MapRegion, region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="map region not found")
    await db.delete(region)
    response = {"ok": True, "region_id": str(region_id)}
    _publish_map_change("map_region_deleted", response)
    return response


@router.get(
    "/points",
    summary="查询地图点位",
    description="按点位编码排序返回当前项目中已持久化的全部地图业务点位。调用方需要具备地图读取权限。",
    response_description="地图点位列表",
)
async def list_points(db: AsyncSession = Depends(get_db), _role=Depends(require("map.read"))) -> list[dict]:
    return [_point_dict(point) for point in (await db.execute(select(MapPoint).order_by(MapPoint.code))).scalars().all()]


@router.post(
    "/points",
    summary="创建地图点位",
    description="在地图坐标系中创建一个业务点位。点位编码必须唯一，调用方需要具备地图管理权限。",
    response_description="创建成功后的地图点位",
    openapi_extra={"requestBody": {"description": "待创建的地图点位参数"}},
)
async def create_point(
    req: Annotated[MapPointInput, Body(description="待创建的地图点位参数")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.manage")),
) -> dict:
    existing = await db.scalar(select(MapPoint).where(MapPoint.code == req.code))
    if existing:
        raise HTTPException(status_code=409, detail="map point code already exists")
    point = MapPoint(**req.model_dump())
    db.add(point)
    await db.flush()
    response = _point_dict(point)
    _publish_map_change("map_point_created", response)
    return response


@router.put(
    "/points/{point_id}",
    summary="更新地图点位",
    description="使用完整点位参数替换指定地图点位的业务属性、坐标和标记配置。调用方需要具备地图管理权限。",
    response_description="更新后的地图点位",
    openapi_extra={"requestBody": {"description": "地图点位的完整更新参数"}},
)
async def update_point(
    point_id: Annotated[uuid.UUID, Path(description="待更新地图点位的 UUID")],
    req: Annotated[MapPointInput, Body(description="地图点位的完整更新参数")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.manage")),
) -> dict:
    point = await db.get(MapPoint, point_id)
    if point is None:
        raise HTTPException(status_code=404, detail="map point not found")
    for field, value in req.model_dump().items():
        setattr(point, field, value)
    await db.flush()
    response = _point_dict(point)
    _publish_map_change("map_point_updated", response)
    return response


@router.delete(
    "/points/{point_id}",
    summary="删除地图点位",
    description="删除未被任务引用的地图点位；已关联任务的点位不能删除。调用方需要具备地图管理权限。",
    response_description="删除结果及已删除的点位 UUID",
)
async def delete_point(
    point_id: Annotated[uuid.UUID, Path(description="待删除地图点位的 UUID")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.manage")),
) -> dict:
    point = await db.get(MapPoint, point_id)
    if point is None:
        raise HTTPException(status_code=404, detail="map point not found")
    task = await db.scalar(select(Task.id).where(Task.map_point_id == point_id).limit(1))
    if task is not None:
        raise HTTPException(status_code=409, detail="map point is referenced by a task and cannot be deleted")
    await db.delete(point)
    response = {"ok": True, "point_id": str(point_id)}
    _publish_map_change("map_point_deleted", response)
    return response


@router.post(
    "/gateway/assets",
    summary="登记外部地图资产",
    description="供机器人、Gazebo 桥接器或外部映射流水线登记已生成的地图资产引用。接口按事件标识幂等，调用时必须提供有效的设备网关 API 密钥。",
    response_description="登记结果；重复事件会返回已有资产并标记为重复",
    openapi_extra={"requestBody": {"description": "外部映射流水线生成的地图资产登记信息"}},
)
async def register_map_asset(
    req: Annotated[MapAssetIn, Body(description="外部映射流水线生成的地图资产登记信息")],
    db: AsyncSession = Depends(get_db),
    _gateway: None = Depends(require_gateway_api_key),
) -> dict:
    """Register a versioned mesh/occupancy asset produced outside this API."""

    asset = await db.scalar(select(MapAsset).where(MapAsset.event_id == req.event_id))
    if asset is not None:
        return {"ok": True, "duplicate": True, "asset": _asset_dict(asset)}
    asset = MapAsset(
        **req.model_dump(exclude={"metadata"}),
        asset_metadata=req.metadata,
    )
    db.add(asset)
    await db.flush()
    response = {"ok": True, "asset": _asset_dict(asset)}
    _publish_map_change("map_asset_registered", response)
    return response


@router.get(
    "/assets",
    summary="查询地图资产",
    description="按观测时间倒序返回已登记的地图资产，可按资产格式筛选。调用方需要具备地图读取权限。",
    response_description="符合筛选条件的地图资产列表",
)
async def list_map_assets(
    asset_type: Annotated[
        Literal["mesh_gltf", "octomap", "geojson"] | None,
        Query(description="按地图资产格式筛选；不传时返回全部格式"),
    ] = None,
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.read")),
) -> list[dict]:
    statement = select(MapAsset)
    if asset_type:
        statement = statement.where(MapAsset.asset_type == asset_type)
    assets = await db.execute(statement.order_by(MapAsset.observed_at.desc()))
    return [_asset_dict(asset) for asset in assets.scalars().all()]


@router.get(
    "/scene-config",
    summary="获取地图场景配置",
    description="返回数据库中已持久化的区域、点位和外部地图资产，用于客户端组装地图场景；接口不会生成临时几何数据。调用方需要具备地图读取权限。",
    response_description="地图场景所需的区域、点位、资产和默认坐标系",
)
async def scene_config(db: AsyncSession = Depends(get_db), _role=Depends(require("map.read"))) -> dict:
    """Return only persisted geometry. Mesh/point-cloud assets are supplied by external mapping jobs."""
    regions = (await db.execute(select(MapRegion).order_by(MapRegion.code))).scalars().all()
    points = (await db.execute(select(MapPoint).order_by(MapPoint.code))).scalars().all()
    assets = (await db.execute(select(MapAsset).order_by(MapAsset.observed_at.desc()))).scalars().all()
    return {
        "regions": [_region_dict(region) for region in regions],
        "points": [_point_dict(point) for point in points],
        "assets": [_asset_dict(asset) for asset in assets],
        "frame_id": "map",
    }
