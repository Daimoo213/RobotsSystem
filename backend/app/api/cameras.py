"""Real camera/vision gateway ingress. The backend never generates detections."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.devices import require_gateway_api_key
from app.core.database import get_db
from app.core.security import require
from app.models.models import Camera, CameraDetection

router = APIRouter(prefix="/cameras", tags=["cameras"])


class CameraRegistration(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    location: str = Field(min_length=1, max_length=128)
    stream_url: str | None = Field(default=None, max_length=512)
    position_x: float = 0.0
    position_y: float = 0.0


class DetectionReport(BaseModel):
    detected_at: datetime
    excavator_count: int = Field(ge=0)
    truck_count: int = Field(ge=0)
    person_count: int = Field(ge=0)
    dust_level: str = Field(min_length=1, max_length=16)
    slope_risk: str = Field(min_length=1, max_length=16)
    ai_compliance_rate: float = Field(ge=0, le=100)


def _camera_dict(camera: Camera) -> dict:
    return {
        "id": str(camera.id), "code": camera.code, "name": camera.name,
        "location": camera.location, "stream_url": camera.stream_url,
        "position": {"x": camera.position_x, "y": camera.position_y}, "is_online": camera.is_online,
    }


@router.post("/gateway/register")
async def register_camera(req: CameraRegistration, db: AsyncSession = Depends(get_db), _gateway: None = Depends(require_gateway_api_key)) -> dict:
    camera = await db.scalar(select(Camera).where(Camera.code == req.code))
    if camera is None:
        camera = Camera(**req.model_dump(), is_online=True)
        db.add(camera)
    else:
        for field, value in req.model_dump().items():
            setattr(camera, field, value)
        camera.is_online = True
    await db.flush()
    return _camera_dict(camera)


@router.post("/gateway/{camera_code}/detections")
async def report_detection(camera_code: str, req: DetectionReport, db: AsyncSession = Depends(get_db), _gateway: None = Depends(require_gateway_api_key)) -> dict:
    camera = await db.scalar(select(Camera).where(Camera.code == camera_code))
    if camera is None:
        raise HTTPException(status_code=404, detail="camera is not registered")
    camera.is_online = True
    detection = CameraDetection(camera_id=camera.id, **req.model_dump())
    db.add(detection)
    await db.flush()
    return {"id": str(detection.id), "camera_code": camera.code, "detected_at": detection.detected_at.isoformat()}


@router.get("")
async def list_cameras(db: AsyncSession = Depends(get_db), _role=Depends(require("read"))) -> list[dict]:
    return [_camera_dict(camera) for camera in (await db.execute(select(Camera).order_by(Camera.code))).scalars().all()]
