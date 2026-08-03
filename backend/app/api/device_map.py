"""Robot-facing map discovery and complete point-cloud download APIs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.devices import DEVICE_CODE_PATTERN, _require_device_key
from app.api.map import _asset_dict, _path_dict, _point_dict, _region_dict
from app.api.pointcloud import _map_dict
from app.core.config import settings
from app.core.database import get_db
from app.models.models import Device, MapAsset, MapPath, MapPoint, MapRegion, PointCloudMap, Project


router = APIRouter(prefix="/devices/gateway", tags=["devices"])
device_gateway_key_scheme = APIKeyHeader(
    name="X-Device-Gateway-Key",
    scheme_name="DeviceGatewayKey",
    auto_error=False,
    description="设备首次注册时获得的专属网关密钥；共享初始化密钥不能替代。",
)


class MapCoordinateSystem(BaseModel):
    handedness: Literal["right"] = Field(description="坐标系手性；当前固定为右手坐标系。")
    unit: Literal["m"] = Field(description="X、Y、Z 坐标统一使用的长度单位；当前固定为米。")
    z_axis: Literal["up"] = Field(description="Z 轴正方向；当前固定为竖直向上。")


class GatewayPointCloudManifest(BaseModel):
    has_data: bool = Field(description="当前项目是否已经保存一份完整点云地图。")
    map_id: str | None = Field(description="当前完整点云地图的不可变版本标识；没有点云时为空。")
    source_id: str | None = Field(description="生成当前完整点云地图的设备或建图桥接器标识。")
    frame_id: str = Field(description="点云使用的项目地图坐标系标识。")
    points_count: int = Field(description="当前完整点云地图包含的真实点数量。")
    metadata: dict[str, Any] = Field(description="建图端随当前点云地图提交的真实扩展元数据。")
    observed_at: str | None = Field(description="建图端生成或观测当前点云地图的 ISO 8601 时间。")
    received_at: str | None = Field(description="平台接收当前点云地图的 ISO 8601 时间。")
    download_path: str | None = Field(description="使用设备专属密钥下载当前完整点云地图的相对 API 路径。")


class GatewayMapManifest(BaseModel):
    schema_version: Literal["v1"] = Field(description="机器人地图同步响应结构版本。")
    device_code: str = Field(description="通过鉴权的设备唯一编码。")
    project_code: str = Field(description="当前活动项目的唯一业务编码。")
    project_name: str = Field(description="当前活动项目名称。")
    frame_id: str = Field(description="区域、点位、资产和点云共同使用的项目地图坐标系标识。")
    coordinate_system: MapCoordinateSystem = Field(description="项目地图坐标系的方向和单位约定。")
    sync_revision: str = Field(description="当前整套地图语义内容的 SHA-256 修订号，用于变更检测和原子切换。")
    regions: list[dict[str, Any]] = Field(description="数据库中真实保存的全部三维业务区域，按区域编码稳定排序。")
    points: list[dict[str, Any]] = Field(description="数据库中真实保存的全部业务点位，按点位编码稳定排序。")
    paths: list[dict[str, Any]] = Field(description="数据库中真实保存的机器人通行路径及其高程、方向、宽度、坡度和设备类型约束，按路径编码稳定排序。")
    assets: list[dict[str, Any]] = Field(description="已登记的外部地图资产引用、格式、坐标系和校验值。")
    pointcloud: GatewayPointCloudManifest = Field(description="当前完整点云地图摘要；清单不内嵌大体积点数组。")


class GatewayPointCloudDownload(BaseModel):
    schema_version: Literal["v1"] = Field(description="机器人点云下载响应结构版本。")
    map_id: str = Field(description="本次下载的完整点云地图不可变版本标识。")
    source_id: str = Field(description="生成本次完整点云地图的设备或建图桥接器标识。")
    frame_id: str = Field(description="全部点坐标使用的项目地图坐标系标识。")
    points: list[list[float]] = Field(description="建图端已融合和抽样的完整真实点集，每个点固定为 [x,y,z]。")
    total_count: int = Field(description="完整点云地图的点数量。")
    progress: float = Field(description="完整地图的可用进度；成功下载时固定为 1。")
    metadata: dict[str, Any] = Field(description="建图端随完整点云地图提交的真实扩展元数据。")
    observed_at: str = Field(description="建图端生成或观测该地图的 ISO 8601 时间。")
    received_at: str = Field(description="平台接收该地图的 ISO 8601 时间。")


@dataclass(frozen=True, slots=True)
class DeviceMapSnapshot:
    project: Project
    regions: list[MapRegion]
    points: list[MapPoint]
    assets: list[MapAsset]
    pointcloud: PointCloudMapSummary | None
    paths: list[MapPath] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PointCloudMapSummary:
    map_id: str
    source_id: str
    frame_id: str
    points_count: int
    map_metadata: dict[str, Any]
    observed_at: datetime
    received_at: datetime


def _validate_snapshot_frames(snapshot: DeviceMapSnapshot) -> None:
    expected = snapshot.project.map_frame
    sources: list[tuple[str, str]] = []
    if snapshot.pointcloud is not None:
        sources.append((f"pointcloud:{snapshot.pointcloud.map_id}", snapshot.pointcloud.frame_id))
    sources.extend((f"asset:{asset.event_id}", asset.frame_id) for asset in snapshot.assets)
    mismatch = next(((source, frame_id) for source, frame_id in sources if frame_id != expected), None)
    if mismatch is not None:
        source, frame_id = mismatch
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stored_map_frame_mismatch",
                "message": "已保存地图数据的坐标系与当前项目不一致，已拒绝向机器人下发混合坐标数据。",
                "source": source,
                "expected_frame_id": expected,
                "actual_frame_id": frame_id,
            },
        )


def _pointcloud_manifest(
    pointcloud: PointCloudMapSummary | None,
    frame_id: str,
    device_code: str,
) -> dict[str, Any]:
    if pointcloud is None:
        return {
            "has_data": False,
            "map_id": None,
            "source_id": None,
            "frame_id": frame_id,
            "points_count": 0,
            "metadata": {},
            "observed_at": None,
            "received_at": None,
            "download_path": None,
        }
    encoded_device = quote(device_code, safe="")
    encoded_map = quote(pointcloud.map_id, safe="")
    return {
        "has_data": True,
        "map_id": pointcloud.map_id,
        "source_id": pointcloud.source_id,
        "frame_id": pointcloud.frame_id,
        "points_count": pointcloud.points_count,
        "metadata": pointcloud.map_metadata or {},
        "observed_at": pointcloud.observed_at.isoformat(),
        "received_at": pointcloud.received_at.isoformat(),
        "download_path": f"{settings.api_prefix}/devices/gateway/{encoded_device}/map-sync/pointcloud?map_id={encoded_map}",
    }


def _revision_payload(snapshot: DeviceMapSnapshot) -> dict[str, Any]:
    """Return a canonical representation without embedding the complete point array."""

    pointcloud = _pointcloud_manifest(snapshot.pointcloud, snapshot.project.map_frame, "")
    pointcloud.pop("download_path", None)
    return {
        "schema_version": "v1",
        "project_code": snapshot.project.code,
        "frame_id": snapshot.project.map_frame,
        "regions": [_region_dict(region) for region in sorted(snapshot.regions, key=lambda item: item.code)],
        "points": [_point_dict(point) for point in sorted(snapshot.points, key=lambda item: item.code)],
        "paths": [_path_dict(path) for path in sorted(snapshot.paths, key=lambda item: item.code)],
        "assets": [
            _asset_dict(asset)
            for asset in sorted(snapshot.assets, key=lambda item: (item.asset_type, item.event_id))
        ],
        "pointcloud": pointcloud,
    }


def map_sync_revision(snapshot: DeviceMapSnapshot) -> str:
    payload = json.dumps(
        _revision_payload(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _representation_etag(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f'"{prefix}-{hashlib.sha256(encoded).hexdigest()}"'


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    for candidate in if_none_match.split(","):
        normalized = candidate.strip()
        if normalized == "*" or normalized.removeprefix("W/") == etag:
            return True
    return False


async def _start_consistent_read(db: AsyncSession) -> None:
    """Pin auth and map reads to one PostgreSQL repeatable-read snapshot."""

    await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})


async def _single_project(db: AsyncSession) -> Project:
    projects = (await db.execute(select(Project).order_by(Project.created_at).limit(2))).scalars().all()
    if not projects:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目尚未初始化，机器人无法获取地图。")
    if len(projects) != 1 or not projects[0].is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "project_scope_ambiguous",
                "message": "当前数据库不满足单项目运行约束，已拒绝向机器人下发可能混合的地图数据。",
            },
        )
    return projects[0]


def _pointcloud_summary_statement():
    return select(
        PointCloudMap.map_id,
        PointCloudMap.source_id,
        PointCloudMap.frame_id,
        func.jsonb_array_length(PointCloudMap.points).label("points_count"),
        PointCloudMap.map_metadata,
        PointCloudMap.observed_at,
        PointCloudMap.received_at,
    ).where(PointCloudMap.scope == "current")


async def _load_map_snapshot(db: AsyncSession) -> DeviceMapSnapshot:
    project = await _single_project(db)
    regions = (await db.execute(select(MapRegion).order_by(MapRegion.code))).scalars().all()
    points = (await db.execute(select(MapPoint).order_by(MapPoint.code))).scalars().all()
    assets = (
        await db.execute(select(MapAsset).order_by(MapAsset.asset_type, MapAsset.event_id))
    ).scalars().all()
    pointcloud_row = (await db.execute(_pointcloud_summary_statement())).mappings().one_or_none()
    pointcloud = PointCloudMapSummary(**dict(pointcloud_row)) if pointcloud_row is not None else None
    paths = (await db.execute(select(MapPath).order_by(MapPath.code))).scalars().all()
    snapshot = DeviceMapSnapshot(project, list(regions), list(points), list(assets), pointcloud, list(paths))
    _validate_snapshot_frames(snapshot)
    return snapshot


def _manifest(snapshot: DeviceMapSnapshot, device: Device) -> GatewayMapManifest:
    return GatewayMapManifest(
        schema_version="v1",
        device_code=device.code,
        project_code=snapshot.project.code,
        project_name=snapshot.project.name,
        frame_id=snapshot.project.map_frame,
        coordinate_system=MapCoordinateSystem(handedness="right", unit="m", z_axis="up"),
        sync_revision=map_sync_revision(snapshot),
        regions=[_region_dict(region) for region in snapshot.regions],
        points=[_point_dict(point) for point in snapshot.points],
        paths=[_path_dict(path) for path in snapshot.paths],
        assets=[_asset_dict(asset) for asset in snapshot.assets],
        pointcloud=_pointcloud_manifest(snapshot.pointcloud, snapshot.project.map_frame, device.code),
    )


@router.get(
    "/{device_code}/map-sync",
    response_model=GatewayMapManifest,
    summary="获取机器人地图同步清单",
    description=(
        "供已注册且启用的机器人使用设备专属网关密钥读取当前项目的真实区域、点位、地图资产引用和完整点云摘要。"
        "响应使用稳定修订号和 ETag；清单不包含完整点数组。"
    ),
    response_description="当前机器人可同步的地图清单和整图修订号。",
    responses={
        200: {
            "description": "当前机器人可同步的地图清单和整图修订号。",
            "headers": {
                "ETag": {"description": "当前清单完整响应的强校验标签。", "schema": {"type": "string"}},
                "X-Map-Sync-Revision": {"description": "当前地图业务内容修订号。", "schema": {"type": "string"}},
            },
        },
        304: {"description": "客户端持有的地图清单响应仍为最新，无需重复下载。"},
        401: {"description": "设备专属密钥缺失或无效。"},
        403: {"description": "设备网关已被禁用。"},
        404: {"description": "设备编码尚未注册。"},
        409: {"description": "项目范围或持久化地图坐标系存在冲突。"},
    },
)
async def get_gateway_map_sync(
    device_code: Annotated[
        str,
        Path(description="已注册机器人的唯一设备编码。", pattern=DEVICE_CODE_PATTERN),
    ],
    response: Response,
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: Annotated[
        str | None,
        Security(device_gateway_key_scheme),
    ] = None,
    if_none_match: Annotated[
        str | None,
        Header(alias="If-None-Match", description="上一次清单响应返回的 ETag；匹配时返回 304。"),
    ] = None,
) -> GatewayMapManifest | Response:
    await _start_consistent_read(db)
    device = await _require_device_key(db, device_code, x_device_gateway_key)
    manifest = _manifest(await _load_map_snapshot(db), device)
    etag = _representation_etag("map-sync", manifest.model_dump(mode="json"))
    headers = {"ETag": etag, "Cache-Control": "private, no-cache", "X-Map-Sync-Revision": manifest.sync_revision}
    if _etag_matches(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    for name, value in headers.items():
        response.headers[name] = value
    return manifest


@router.get(
    "/{device_code}/map-sync/pointcloud",
    response_model=GatewayPointCloudDownload,
    summary="下载机器人当前完整点云地图",
    description=(
        "供机器人使用设备专属网关密钥按地图版本下载完整真实点云。"
        "请求版本不再是当前版本时返回 409，机器人必须重新获取同步清单，不能静默使用过期地图。"
    ),
    response_description="指定当前版本的完整点云地图和建图元数据。",
    responses={
        200: {
            "description": "指定当前版本的完整点云地图和建图元数据。",
            "headers": {
                "ETag": {"description": "完整点云响应内容的强校验标签。", "schema": {"type": "string"}},
            },
        },
        304: {"description": "客户端已经持有完全相同的点云响应，无需重复下载。"},
        401: {"description": "设备专属密钥缺失或无效。"},
        403: {"description": "设备网关已被禁用。"},
        404: {"description": "当前项目尚无完整点云地图。"},
        409: {"description": "项目未初始化、地图版本已变化或持久化坐标系不一致。"},
    },
)
async def download_gateway_pointcloud(
    device_code: Annotated[
        str,
        Path(description="已注册机器人的唯一设备编码。", pattern=DEVICE_CODE_PATTERN),
    ],
    response: Response,
    map_id: Annotated[
        str,
        Query(description="地图同步清单中返回的当前完整点云 map_id。", min_length=1, max_length=96),
    ],
    db: AsyncSession = Depends(get_db),
    x_device_gateway_key: Annotated[
        str | None,
        Security(device_gateway_key_scheme),
    ] = None,
    if_none_match: Annotated[
        str | None,
        Header(alias="If-None-Match", description="上一次点云下载响应返回的 ETag；匹配时返回 304。"),
    ] = None,
) -> GatewayPointCloudDownload | Response:
    await _start_consistent_read(db)
    await _require_device_key(db, device_code, x_device_gateway_key)
    project = await _single_project(db)
    pointcloud = await db.scalar(select(PointCloudMap).where(PointCloudMap.scope == "current"))
    if pointcloud is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="当前项目尚无完整点云地图。")
    if pointcloud.frame_id != project.map_frame:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stored_map_frame_mismatch",
                "message": "当前点云坐标系与项目地图坐标系不一致，已拒绝下载。",
                "expected_frame_id": project.map_frame,
                "actual_frame_id": pointcloud.frame_id,
            },
        )
    if pointcloud.map_id != map_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "map_version_changed",
                "message": "请求的点云地图已不是当前版本，请重新获取地图同步清单。",
                "requested_map_id": map_id,
                "current_map_id": pointcloud.map_id,
            },
        )
    pointcloud_response = GatewayPointCloudDownload(schema_version="v1", **_map_dict(pointcloud))
    etag = _representation_etag("pointcloud", pointcloud_response.model_dump(mode="json"))
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if _etag_matches(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    for name, value in headers.items():
        response.headers[name] = value
    return pointcloud_response
