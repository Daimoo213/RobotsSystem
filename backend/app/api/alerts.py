"""Alerts router — list / acknowledge."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require
from app.models.models import Alert
from app.services.alert_engine import serialize_alert
from app.ws.router import broadcast_to_ws
from app.core.redis import CHANNEL_ALERTS

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
async def list_alerts(
    level: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
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


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: uuid.UUID,
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
