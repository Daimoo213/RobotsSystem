"""Project map regions and points persisted by authorized operators or import jobs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.devices import require_gateway_api_key
from app.core.database import get_db
from app.core.security import require
from app.models.models import MapAsset, MapPoint, MapRegion, Task

router = APIRouter(prefix="/map", tags=["map"])


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
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    region_type: str = Field(min_length=1, max_length=32)
    polygon: list[list[float]]
    stage: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def validate_geometry(self) -> "MapRegionInput":
        _validate_polygon(self.polygon)
        return self


class MapPointInput(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    point_type: str = Field(min_length=1, max_length=32)
    x: float
    y: float
    z: float = 0.0
    process_type: str | None = Field(default=None, max_length=32)
    device_types: list[str] = Field(default_factory=list)
    stage: str | None = Field(default=None, max_length=32)
    qrcode_id: str | None = Field(default=None, min_length=1, max_length=96)
    qrcode_type: str | None = Field(default=None, max_length=32)


class MapAssetIn(BaseModel):
    """Reference to a map product owned by the external mapping pipeline."""

    event_id: str = Field(min_length=1, max_length=96)
    source_id: str = Field(min_length=1, max_length=96)
    asset_type: Literal["mesh_gltf", "octomap", "geojson"]
    asset_uri: str = Field(min_length=1, max_length=1024)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    frame_id: str = Field(default="map", min_length=1, max_length=64)
    metadata: dict = Field(default_factory=dict)
    observed_at: datetime

    @model_validator(mode="after")
    def validate_asset_reference(self) -> "MapAssetIn":
        _validate_asset_uri(self.asset_uri)
        return self


def _region_dict(region: MapRegion) -> dict:
    return {"id": str(region.id), "code": region.code, "name": region.name, "region_type": region.region_type, "polygon": region.polygon, "stage": region.stage}


def _point_dict(point: MapPoint) -> dict:
    return {"id": str(point.id), "code": point.code, "name": point.name, "point_type": point.point_type, "x": point.x, "y": point.y, "z": point.z, "process_type": point.process_type, "device_types": point.device_types, "stage": point.stage, "qrcode_id": point.qrcode_id, "qrcode_type": point.qrcode_type}


def _asset_dict(asset: MapAsset) -> dict:
    return {
        "id": str(asset.id), "event_id": asset.event_id, "source_id": asset.source_id,
        "asset_type": asset.asset_type, "asset_uri": asset.asset_uri,
        "checksum_sha256": asset.checksum_sha256, "frame_id": asset.frame_id,
        "metadata": asset.asset_metadata or {}, "observed_at": asset.observed_at.isoformat(),
        "received_at": asset.received_at.isoformat(),
    }


@router.get("/regions")
async def list_regions(db: AsyncSession = Depends(get_db), _role=Depends(require("map.read"))) -> list[dict]:
    return [_region_dict(region) for region in (await db.execute(select(MapRegion).order_by(MapRegion.code))).scalars().all()]


@router.post("/regions")
async def create_region(req: MapRegionInput, db: AsyncSession = Depends(get_db), _role=Depends(require("map.manage"))) -> dict:
    existing = await db.scalar(select(MapRegion).where(MapRegion.code == req.code))
    if existing:
        raise HTTPException(status_code=409, detail="map region code already exists")
    region = MapRegion(**req.model_dump())
    db.add(region)
    await db.flush()
    response = _region_dict(region)
    _publish_map_change("map_region_created", response)
    return response


@router.put("/regions/{region_id}")
async def update_region(region_id: uuid.UUID, req: MapRegionInput, db: AsyncSession = Depends(get_db), _role=Depends(require("map.manage"))) -> dict:
    region = await db.get(MapRegion, region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="map region not found")
    for field, value in req.model_dump().items():
        setattr(region, field, value)
    await db.flush()
    response = _region_dict(region)
    _publish_map_change("map_region_updated", response)
    return response


@router.delete("/regions/{region_id}")
async def delete_region(region_id: uuid.UUID, db: AsyncSession = Depends(get_db), _role=Depends(require("map.manage"))) -> dict:
    region = await db.get(MapRegion, region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="map region not found")
    await db.delete(region)
    response = {"ok": True, "region_id": str(region_id)}
    _publish_map_change("map_region_deleted", response)
    return response


@router.get("/points")
async def list_points(db: AsyncSession = Depends(get_db), _role=Depends(require("map.read"))) -> list[dict]:
    return [_point_dict(point) for point in (await db.execute(select(MapPoint).order_by(MapPoint.code))).scalars().all()]


@router.post("/points")
async def create_point(req: MapPointInput, db: AsyncSession = Depends(get_db), _role=Depends(require("map.manage"))) -> dict:
    existing = await db.scalar(select(MapPoint).where(MapPoint.code == req.code))
    if existing:
        raise HTTPException(status_code=409, detail="map point code already exists")
    point = MapPoint(**req.model_dump())
    db.add(point)
    await db.flush()
    response = _point_dict(point)
    _publish_map_change("map_point_created", response)
    return response


@router.put("/points/{point_id}")
async def update_point(point_id: uuid.UUID, req: MapPointInput, db: AsyncSession = Depends(get_db), _role=Depends(require("map.manage"))) -> dict:
    point = await db.get(MapPoint, point_id)
    if point is None:
        raise HTTPException(status_code=404, detail="map point not found")
    for field, value in req.model_dump().items():
        setattr(point, field, value)
    await db.flush()
    response = _point_dict(point)
    _publish_map_change("map_point_updated", response)
    return response


@router.delete("/points/{point_id}")
async def delete_point(point_id: uuid.UUID, db: AsyncSession = Depends(get_db), _role=Depends(require("map.manage"))) -> dict:
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


@router.post("/gateway/assets")
async def register_map_asset(
    req: MapAssetIn,
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


@router.get("/assets")
async def list_map_assets(
    asset_type: Literal["mesh_gltf", "octomap", "geojson"] | None = None,
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("map.read")),
) -> list[dict]:
    statement = select(MapAsset)
    if asset_type:
        statement = statement.where(MapAsset.asset_type == asset_type)
    assets = await db.execute(statement.order_by(MapAsset.observed_at.desc()))
    return [_asset_dict(asset) for asset in assets.scalars().all()]


@router.get("/scene-config")
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
