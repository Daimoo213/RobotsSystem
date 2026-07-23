"""Alerts router — list / acknowledge."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require
from app.models.models import Alert
from app.services.alert_engine import serialize_alert
from app.ws.router import broadcast_to_ws
from app.core.redis import CHANNEL_ALERTS

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get(
    "",
    summary="查询告警列表",
    description="按告警级别和处理状态筛选数据库中的最近 100 条真实告警，结果按创建时间倒序排列。",
    response_description="符合筛选条件的告警记录列表。",
)
async def list_alerts(
    level: str | None = Query(default=None, description="告警级别，例如 info、warning 或 critical。"),
    status_filter: str | None = Query(default=None, alias="status", description="处理状态，例如 open、ack 或 resolved。"),
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("read")),
) -> list[dict]:
    stmt = select(Alert)
    if level:
        stmt = stmt.where(Alert.level == level)
    if status_filter:
        stmt = stmt.where(Alert.status == status_filter)
    result = await db.execute(stmt.order_by(Alert.created_at.desc()).limit(100))
    return [_alert_dict(a) for a in result.scalars().all()]


@router.post(
    "/{alert_id}/acknowledge",
    summary="确认告警",
    description="将指定 open 告警标记为 ack，并将更新后的告警广播给已连接客户端。",
    response_description="确认结果和更新后的告警记录。",
)
async def acknowledge_alert(
    alert_id: uuid.UUID = Path(description="要确认的告警 UUID。"),
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("alert.acknowledge")),
) -> dict:
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="alert not found")
    if a.status == "open":
        a.status = "ack"
        await db.flush()
    payload = _alert_dict(a)
    await broadcast_to_ws(CHANNEL_ALERTS, payload)
    return {"ok": True, "alert": payload}


def _alert_dict(a: Alert) -> dict:
    return serialize_alert(a)
