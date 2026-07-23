"""Real camera/vision gateway ingress. The backend never generates detections."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.devices import require_gateway_api_key
from app.core.database import get_db
from app.core.security import require
from app.models.models import Camera, CameraDetection

router = APIRouter(prefix="/cameras", tags=["cameras"])


class CameraRegistration(BaseModel):
    code: str = Field(description="摄像头唯一业务编码；重复登记同一编码时更新已有设备", min_length=1, max_length=32)
    name: str = Field(description="摄像头显示名称", min_length=1, max_length=64)
    location: str = Field(description="摄像头安装位置或覆盖区域的文字说明", min_length=1, max_length=128)
    stream_url: str | None = Field(description="真实视频流地址，如 RTSP 或受控的流媒体地址；未接入视频流时留空", default=None, max_length=512)
    position_x: float = Field(description="摄像头在地图坐标系中的 X 坐标", default=0.0)
    position_y: float = Field(description="摄像头在地图坐标系中的 Y 坐标", default=0.0)


class DetectionReport(BaseModel):
    detected_at: datetime = Field(description="视觉分析发生时间，使用带时区的 ISO 8601 时间")
    excavator_count: int = Field(description="本次检测画面中的挖掘机数量", ge=0)
    truck_count: int = Field(description="本次检测画面中的运输车辆数量", ge=0)
    person_count: int = Field(description="本次检测画面中的人员数量", ge=0)
    dust_level: str = Field(description="视觉系统判定的扬尘等级，枚举值由设备接入协议约定", min_length=1, max_length=16)
    slope_risk: str = Field(description="视觉系统判定的边坡风险等级，枚举值由设备接入协议约定", min_length=1, max_length=16)
    ai_compliance_rate: float = Field(description="视觉系统计算的作业合规率，取值范围为 0 到 100", ge=0, le=100)


def _camera_dict(camera: Camera) -> dict:
    return {
        "id": str(camera.id), "code": camera.code, "name": camera.name,
        "location": camera.location, "stream_url": camera.stream_url,
        "position": {"x": camera.position_x, "y": camera.position_y}, "is_online": camera.is_online,
    }


@router.post(
    "/gateway/register",
    summary="登记或更新摄像头",
    description="供摄像头网关登记真实设备。摄像头编码已存在时更新设备信息并标记在线，否则创建新记录；调用时必须提供有效的设备网关 API 密钥。",
    response_description="登记或更新后的摄像头信息",
    openapi_extra={"requestBody": {"description": "待登记或更新的摄像头设备信息"}},
)
async def register_camera(
    req: Annotated[CameraRegistration, Body(description="待登记或更新的摄像头设备信息")],
    db: AsyncSession = Depends(get_db),
    _gateway: None = Depends(require_gateway_api_key),
) -> dict:
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


@router.post(
    "/gateway/{camera_code}/detections",
    summary="上报摄像头检测结果",
    description="供视觉网关为已登记摄像头上报一次真实识别统计，并将摄像头标记为在线；调用时必须提供有效的设备网关 API 密钥。",
    response_description="已保存检测记录的标识、摄像头编码和检测时间",
    openapi_extra={"requestBody": {"description": "视觉系统本次检测产生的统计结果"}},
)
async def report_detection(
    camera_code: Annotated[str, Path(description="上报检测结果的摄像头业务编码")],
    req: Annotated[DetectionReport, Body(description="视觉系统本次检测产生的统计结果")],
    db: AsyncSession = Depends(get_db),
    _gateway: None = Depends(require_gateway_api_key),
) -> dict:
    camera = await db.scalar(select(Camera).where(Camera.code == camera_code))
    if camera is None:
        raise HTTPException(status_code=404, detail="camera is not registered")
    camera.is_online = True
    detection = CameraDetection(camera_id=camera.id, **req.model_dump())
    db.add(detection)
    await db.flush()
    return {"id": str(detection.id), "camera_code": camera.code, "detected_at": detection.detected_at.isoformat()}


@router.get(
    "",
    summary="查询摄像头列表",
    description="按摄像头编码排序返回数据库中已登记的全部摄像头及其在线状态。调用方需要具备读取权限。",
    response_description="已登记的摄像头列表",
)
async def list_cameras(db: AsyncSession = Depends(get_db), _role=Depends(require("read"))) -> list[dict]:
    return [_camera_dict(camera) for camera in (await db.execute(select(Camera).order_by(Camera.code))).scalars().all()]
