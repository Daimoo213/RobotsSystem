"""Persistent point-cloud snapshots from external SLAM or Gazebo bridges."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
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
    event_id: str = Field(min_length=1, max_length=96)
    source_id: str = Field(min_length=1, max_length=96)
    frame_id: str = Field(default="map", min_length=1, max_length=64)
    observed_at: datetime
    points: list[list[float]] = Field(min_length=1, max_length=MAX_POINTS_PER_SNAPSHOT)
    metadata: dict = Field(default_factory=dict)

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


@router.post("/gateway/snapshots")
async def ingest_snapshot(
    req: PointCloudSnapshotIn,
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


@router.get("/latest")
async def latest_snapshot(db: AsyncSession = Depends(get_db), _role=Depends(require("read"))) -> dict:
    snapshot = await db.scalar(select(PointCloudSnapshot).order_by(PointCloudSnapshot.observed_at.desc()).limit(1))
    if snapshot is None:
        return {"has_data": False, "points": [], "total_count": 0, "progress": 0.0}
    return {"has_data": True, **_snapshot_dict(snapshot)}


@router.get("/status")
async def status(db: AsyncSession = Depends(get_db), _role=Depends(require("read"))) -> dict:
    snapshot = await db.scalar(select(PointCloudSnapshot).order_by(PointCloudSnapshot.observed_at.desc()).limit(1))
    return {
        "source": snapshot.source_id if snapshot else "not_configured",
        "active": snapshot is not None,
        "points_count": len(snapshot.points) if snapshot else 0,
        "progress": 1.0 if snapshot else 0.0,
        "updated_at": snapshot.observed_at.isoformat() if snapshot else None,
    }
