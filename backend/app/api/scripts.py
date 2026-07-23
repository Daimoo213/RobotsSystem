"""Scripts router — list / activate (stage management)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require
from app.models.models import Script

router = APIRouter(prefix="/scripts", tags=["scripts"])


@router.get(
    "",
    summary="查询施工阶段脚本",
    description="从数据库读取所有施工阶段脚本及当前激活状态，按阶段排序。",
    response_description="施工阶段脚本列表。",
)
async def list_scripts(db: AsyncSession = Depends(get_db),
                      _role=Depends(require("read"))) -> list[dict]:
    result = await db.execute(select(Script).order_by(Script.stage))
    return [_script_dict(s) for s in result.scalars().all()]


@router.post(
    "/{script_id}/activate",
    summary="激活施工阶段脚本",
    description="停用其他脚本并激活指定脚本，然后通知运行时重新加载调度阶段。",
    response_description="激活结果和当前脚本 UUID。",
)
async def activate_script(
    script_id: uuid.UUID = Path(description="要激活的施工阶段脚本 UUID。"),
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("script.activate")),
) -> dict:
    """Activate a script (PM only). Deactivates all others first."""
    await db.execute(update(Script).values(is_active=False))
    await db.execute(update(Script).where(Script.id == script_id).values(is_active=True))
    await db.flush()

    # Notify runtime to reload
    from app.services.runtime import get_runtime
    runtime = get_runtime()
    if runtime:
        await runtime.reload_script(script_id)

    return {"ok": True, "active_script_id": str(script_id)}


def _script_dict(s: Script) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "description": s.description,
        "stage": s.stage,
        "is_active": s.is_active,
    }
