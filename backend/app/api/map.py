"""Project map regions and points persisted by authorized operators or import jobs."""

from __future__ import annotations

import uuid
import math
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.devices import require_gateway_api_key
from app.core.coordinates import MAP_FRAME_CONVENTION, ensure_map_frame
from app.core.database import get_db
from app.core.security import require
from app.models.models import MapAsset, MapPath, MapPoint, MapRegion, Project, Task

router = APIRouter(prefix="/map", tags=["map"])
DEFAULT_MAP_COLOR = "#2FD7FF"
MAX_GRID_SEGMENTS = 20_000
MAX_REGION_VOLUMES = 20_000
MAX_PATH_POINTS = 10_000
MAX_PATH_DEVICE_TYPES = 128


class MapGridConfig(BaseModel):
    """Persisted visual and interaction parameters for the O&M 3D grid."""

    model_config = ConfigDict(extra="forbid")

    origin_x: float = Field(default=-30.0, description="三维栅格最小角的地图 X 坐标，单位为米；不会重新定义项目地图原点")
    origin_y: float = Field(default=-30.0, description="三维栅格最小角的地图 Y 坐标，单位为米；不会重新定义项目地图原点")
    origin_z: float = Field(default=0.0, description="三维栅格底面的地图 Z 高度，单位为米；+Z 竖直向上")
    cell_length: float = Field(default=1.0, gt=0.01, le=100.0, description="单个栅格在 X 方向代表的长度，单位为米")
    cell_width: float = Field(default=1.0, gt=0.01, le=100.0, description="单个栅格在 Y 方向代表的宽度，单位为米")
    cell_height: float = Field(default=0.5, gt=0.01, le=100.0, description="单个栅格在 Z 方向代表的高度，单位为米")
    extent_length: float = Field(default=60.0, gt=0.01, le=1000.0, description="三维栅格在 X 方向显示的总长度，单位为米")
    extent_width: float = Field(default=60.0, gt=0.01, le=1000.0, description="三维栅格在 Y 方向显示的总宽度，单位为米")
    vertical_layers: int = Field(default=6, ge=1, le=200, description="三维栅格显示的垂直层数")
    line_color: str = Field(default="#5BB7FF", pattern=r"^#[0-9a-fA-F]{6}$", description="三维栅格线条的六位十六进制颜色")
    line_thickness: float = Field(default=0.04, gt=0.001, le=1.0, description="三维栅格线条的真实空间粗细，单位为米")
    opacity: float = Field(default=0.38, gt=0.01, le=1.0, description="三维栅格线条透明度")

    @model_validator(mode="after")
    def validate_grid_complexity(self) -> "MapGridConfig":
        columns = math.ceil(self.extent_length / self.cell_length)
        rows = math.ceil(self.extent_width / self.cell_width)
        segments = (columns + 1) * (rows + 1) + (columns + rows + 2) * (self.vertical_layers + 1)
        if segments > MAX_GRID_SEGMENTS:
            raise ValueError(f"当前栅格配置会生成超过 {MAX_GRID_SEGMENTS} 条线段，请增大栅格尺寸或缩小显示范围")
        return self


DEFAULT_GRID_CONFIG = MapGridConfig().model_dump()


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


class MapRegionVolumeInput(BaseModel):
    """One connected three-dimensional component of a logical map region."""

    model_config = ConfigDict(extra="forbid")

    polygon: list[list[float]] = Field(description="区域组件边界顶点，使用地图坐标系下的 [x, y] 坐标")
    min_z: float = Field(description="区域组件底部高度，使用地图坐标系 Z 轴，单位为米")
    max_z: float = Field(description="区域组件顶部高度，使用地图坐标系 Z 轴，单位为米")

    @model_validator(mode="after")
    def validate_geometry(self) -> "MapRegionVolumeInput":
        _validate_polygon(self.polygon)
        if self.max_z <= self.min_z:
            raise ValueError("区域组件顶部高度必须大于底部高度")
        return self


class MapRegionInput(BaseModel):
    code: str = Field(description="区域唯一业务编码，同一项目内不可重复", min_length=1, max_length=32)
    name: str = Field(description="区域显示名称", min_length=1, max_length=64)
    region_type: str = Field(description="区域类型，由项目按业务场景约定，如作业区或禁行区", min_length=1, max_length=32)
    polygon: list[list[float]] = Field(description="区域边界顶点，使用地图坐标系下的 [x, y] 坐标，至少三个点且围成的面积非零")
    min_z: float = Field(description="区域体积的底部高度，使用地图坐标系 Z 轴，单位为米", default=0.0)
    max_z: float = Field(description="区域体积的顶部高度，使用地图坐标系 Z 轴，单位为米", default=0.5)
    volumes: list[MapRegionVolumeInput] = Field(description="同一逻辑区域的多个三维体积组件；未提供时使用 polygon、min_z 和 max_z 表示单个组件，最多 20000 个", default_factory=list, max_length=MAX_REGION_VOLUMES)
    stage: str | None = Field(description="区域所属施工阶段或业务阶段；不分阶段时留空", default=None, max_length=32)
    color: str = Field(description="区域在地图栅格上显示的六位十六进制边线颜色", default=DEFAULT_MAP_COLOR, pattern=r"^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def validate_geometry(self) -> "MapRegionInput":
        _validate_polygon(self.polygon)
        if self.max_z <= self.min_z:
            raise ValueError("区域顶部高度必须大于底部高度")
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


class MapPathInput(BaseModel):
    """A traversable robot route stored as ordered three-dimensional map points."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(description="路径唯一业务编码，同一项目内不可重复", min_length=1, max_length=32)
    name: str = Field(description="路径显示名称", min_length=1, max_length=64)
    points: list[list[float]] = Field(
        description=(
            "按通行顺序排列的连续三维地图坐标点，每个点固定为 [x, y, z]，单位为米；"
            "z 表示高程，相邻点的高程差用于表达上下坡"
        ),
        min_length=2,
        max_length=MAX_PATH_POINTS,
    )
    direction: Literal["bidirectional", "forward", "reverse"] = Field(
        default="bidirectional",
        description=(
            "通行方向：bidirectional 表示双向；forward 仅允许按 points 的首点至末点通行；"
            "reverse 仅允许按末点至首点通行"
        ),
    )
    min_width_m: float = Field(
        description="机器人通行所需的最小净宽，单位为米",
        gt=0.05,
        le=100.0,
    )
    max_slope_percent: float = Field(
        description="允许的最大坡度百分比；服务端会校验每个连续路径段的实际坡度不超过此值",
        ge=0.0,
        le=100.0,
    )
    device_types: list[str] = Field(
        description="允许通行的设备类型编码；空数组表示平台不限制设备类型，设备仍须自行执行本体安全校验",
        default_factory=list,
        max_length=MAX_PATH_DEVICE_TYPES,
    )
    status: Literal["active", "disabled"] = Field(
        default="active",
        description="路径状态：active 可下发使用；disabled 保留历史几何但设备不得将其作为可通行路径",
    )

    @model_validator(mode="after")
    def validate_route_geometry(self) -> "MapPathInput":
        normalized_types: list[str] = []
        seen_types: set[str] = set()
        for device_type in self.device_types:
            if not device_type or len(device_type) > 32:
                raise ValueError("可通行设备类型编码必须为 1 到 32 个字符")
            if device_type in seen_types:
                raise ValueError("可通行设备类型编码不能重复")
            seen_types.add(device_type)
            normalized_types.append(device_type)
        self.device_types = normalized_types

        max_actual_slope = 0.0
        previous: list[float] | None = None
        for index, point in enumerate(self.points):
            if len(point) != 3 or any(not math.isfinite(value) for value in point):
                raise ValueError(f"第 {index + 1} 个路径点必须是三个有限的 [x, y, z] 数值")
            if previous is not None:
                horizontal_distance = math.hypot(point[0] - previous[0], point[1] - previous[1])
                if horizontal_distance <= 1e-6:
                    raise ValueError("相邻路径点的水平位置不能重合，路径不能包含垂直段或重复点")
                max_actual_slope = max(max_actual_slope, abs(point[2] - previous[2]) / horizontal_distance * 100)
            previous = point
        if max_actual_slope > self.max_slope_percent + 1e-9:
            raise ValueError("路径实际坡度超过填写的最大坡度百分比")
        return self


class MapAssetIn(BaseModel):
    """Reference to a map product owned by the external mapping pipeline."""

    event_id: str = Field(description="上游映射流水线生成的幂等事件标识；重复提交同一标识不会重复入库", min_length=1, max_length=96)
    source_id: str = Field(description="生成地图资产的机器人、仿真桥接器或映射任务标识", min_length=1, max_length=96)
    asset_type: Literal["mesh_gltf", "octomap", "geojson"] = Field(description="地图资产格式：GLTF 网格、OctoMap 占据地图或 GeoJSON 地理数据")
    asset_uri: str = Field(description="资产文件的绝对访问地址，仅接受 HTTPS 或 s3、gs、oss 对象存储 URI", min_length=1, max_length=1024)
    checksum_sha256: str | None = Field(description="资产文件的 SHA-256 校验值，使用 64 位十六进制字符串；未提供校验值时留空", default=None, pattern=r"^[0-9a-fA-F]{64}$")
    frame_id: str = Field(description=f"资产使用的项目地图坐标系标识。{MAP_FRAME_CONVENTION}", default="map", min_length=1, max_length=64)
    metadata: dict = Field(description="上游系统附带的扩展元数据，字段由设备集成协议约定", default_factory=dict)
    observed_at: datetime = Field(description="上游系统生成或观测到该资产的时间，使用带时区的 ISO 8601 时间")

    @model_validator(mode="after")
    def validate_asset_reference(self) -> "MapAssetIn":
        _validate_asset_uri(self.asset_uri)
        return self


def _region_dict(region: MapRegion) -> dict:
    volumes = region.volumes or [{"polygon": region.polygon, "min_z": region.min_z, "max_z": region.max_z}]
    return {
        "id": str(region.id), "code": region.code, "name": region.name,
        "region_type": region.region_type, "polygon": region.polygon,
        "min_z": region.min_z, "max_z": region.max_z,
        "volumes": volumes,
        "stage": region.stage, "color": region.color,
    }


def _point_dict(point: MapPoint) -> dict:
    return {"id": str(point.id), "code": point.code, "name": point.name, "point_type": point.point_type, "x": point.x, "y": point.y, "z": point.z, "process_type": point.process_type, "device_types": point.device_types, "stage": point.stage, "qrcode_id": point.qrcode_id, "qrcode_type": point.qrcode_type, "color": point.color}


def _path_dict(path: MapPath) -> dict:
    return {
        "id": str(path.id),
        "code": path.code,
        "name": path.name,
        "points": path.points,
        "direction": path.direction,
        "min_width_m": path.min_width_m,
        "max_slope_percent": path.max_slope_percent,
        "device_types": path.device_types or [],
        "status": path.status,
    }


def _asset_dict(asset: MapAsset) -> dict:
    return {
        "id": str(asset.id), "event_id": asset.event_id, "source_id": asset.source_id,
        "asset_type": asset.asset_type, "asset_uri": asset.asset_uri,
        "checksum_sha256": asset.checksum_sha256, "frame_id": asset.frame_id,
        "metadata": asset.asset_metadata or {}, "observed_at": asset.observed_at.isoformat(),
        "received_at": asset.received_at.isoformat(),
    }


async def _active_project(db: AsyncSession) -> Project:
    project = await db.scalar(
        select(Project).where(Project.is_active.is_(True)).order_by(Project.created_at.desc()).limit(1)
    )
    if project is None:
        raise HTTPException(status_code=409, detail="项目尚未初始化，不能读取或设置地图栅格")
    return project


def _grid_config(project: Project) -> MapGridConfig:
    return MapGridConfig.model_validate({**DEFAULT_GRID_CONFIG, **(project.map_grid_config or {})})


@router.get(
    "/grid-config",
    summary="获取三维栅格地图配置",
    description="读取当前项目持久化的三维栅格尺寸、显示范围、线条样式和透明度。调用方需要具备地图读取权限。",
    response_description="当前项目的三维栅格地图配置",
)
async def get_grid_config(db: AsyncSession = Depends(get_db), _role=Depends(require("map.read"))) -> dict:
    return _grid_config(await _active_project(db)).model_dump()


@router.put(
    "/grid-config",
    summary="更新三维栅格地图配置",
    description="保存当前项目的三维栅格尺寸、显示范围与线条样式。仅 O&M 可修改；配置会同步给所有已登录的地图视图。",
    response_description="保存后的三维栅格地图配置",
)
async def update_grid_config(
    req: Annotated[MapGridConfig, Body(description="要保存的三维栅格地图完整配置")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.manage")),
) -> dict:
    project = await _active_project(db)
    project.map_grid_config = req.model_dump()
    await db.flush()
    response = req.model_dump()
    _publish_map_change("map_grid_config_updated", response)
    return response


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
    values = req.model_dump()
    if values["volumes"]:
        first_volume = values["volumes"][0]
        values.update(
            polygon=first_volume["polygon"],
            min_z=first_volume["min_z"],
            max_z=first_volume["max_z"],
        )
    region = MapRegion(**values)
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
    values = req.model_dump()
    if values["volumes"]:
        first_volume = values["volumes"][0]
        values.update(
            polygon=first_volume["polygon"],
            min_z=first_volume["min_z"],
            max_z=first_volume["max_z"],
        )
    for field, value in values.items():
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


@router.get(
    "/paths",
    summary="查询机器人通行路径",
    description="由 O&M 按路径编码返回当前项目已持久化的机器人通行路径、三维高程、坡度约束和设备适用范围。调用方需要具备地图管理权限。",
    response_description="机器人通行路径列表；不会生成任何占位路径。",
)
async def list_paths(db: AsyncSession = Depends(get_db), _role=Depends(require("map.manage"))) -> list[dict]:
    paths = await db.execute(select(MapPath).order_by(MapPath.code))
    return [_path_dict(path) for path in paths.scalars().all()]


@router.post(
    "/paths",
    summary="创建机器人通行路径",
    description="由 O&M 保存一条实际测绘或现场确认的通行路径。路径使用有序 [x, y, z] 点列，其中 z 为高程；服务端校验坡度和连续性。",
    response_description="创建成功后的机器人通行路径。",
    openapi_extra={"requestBody": {"description": "待保存的完整机器人通行路径与通行约束"}},
)
async def create_path(
    req: Annotated[MapPathInput, Body(description="待保存的完整机器人通行路径与通行约束")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.manage")),
) -> dict:
    existing = await db.scalar(select(MapPath).where(MapPath.code == req.code))
    if existing is not None:
        raise HTTPException(status_code=409, detail="路径编码已存在")
    path = MapPath(**req.model_dump())
    db.add(path)
    await db.flush()
    response = _path_dict(path)
    _publish_map_change("map_path_created", response)
    return response


@router.put(
    "/paths/{path_id}",
    summary="更新机器人通行路径",
    description="由 O&M 使用完整参数替换指定路径的几何、方向、宽度、坡度、设备类型和状态。更新后设备下次地图同步会取得新版本。",
    response_description="更新后的机器人通行路径。",
    openapi_extra={"requestBody": {"description": "机器人通行路径的完整更新参数"}},
)
async def update_path(
    path_id: Annotated[uuid.UUID, Path(description="待更新机器人通行路径的 UUID")],
    req: Annotated[MapPathInput, Body(description="机器人通行路径的完整更新参数")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.manage")),
) -> dict:
    path = await db.get(MapPath, path_id)
    if path is None:
        raise HTTPException(status_code=404, detail="机器人通行路径不存在")
    duplicate = await db.scalar(select(MapPath.id).where(MapPath.code == req.code, MapPath.id != path_id))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="路径编码已存在")
    for field, value in req.model_dump().items():
        setattr(path, field, value)
    await db.flush()
    response = _path_dict(path)
    _publish_map_change("map_path_updated", response)
    return response


@router.delete(
    "/paths/{path_id}",
    summary="删除机器人通行路径",
    description="由 O&M 永久删除一条不再适用的机器人通行路径。删除后设备下次地图同步不再收到该路径。",
    response_description="删除结果和已删除路径 UUID。",
)
async def delete_path(
    path_id: Annotated[uuid.UUID, Path(description="待删除机器人通行路径的 UUID")],
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.manage")),
) -> dict:
    path = await db.get(MapPath, path_id)
    if path is None:
        raise HTTPException(status_code=404, detail="机器人通行路径不存在")
    await db.delete(path)
    response = {"ok": True, "path_id": str(path_id)}
    _publish_map_change("map_path_deleted", response)
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

    project = await _active_project(db)
    ensure_map_frame(req.frame_id, project.map_frame)
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
    project = await _active_project(db)
    regions = (await db.execute(select(MapRegion).order_by(MapRegion.code))).scalars().all()
    points = (await db.execute(select(MapPoint).order_by(MapPoint.code))).scalars().all()
    paths = (await db.execute(select(MapPath).order_by(MapPath.code))).scalars().all()
    assets = (await db.execute(select(MapAsset).order_by(MapAsset.observed_at.desc()))).scalars().all()
    return {
        "regions": [_region_dict(region) for region in regions],
        "points": [_point_dict(point) for point in points],
        "paths": [_path_dict(path) for path in paths],
        "assets": [_asset_dict(asset) for asset in assets],
        "frame_id": project.map_frame,
        "grid_config": _grid_config(project).model_dump(),
    }
