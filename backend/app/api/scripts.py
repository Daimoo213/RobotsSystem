"""Scripts router — list / activate (stage management)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require
from app.models.models import Script

router = APIRouter(prefix="/scripts", tags=["scripts"])


@router.get("")
async def list_scripts(db: AsyncSession = Depends(get_db),
                      _role=Depends(require("read"))) -> list[dict]:
    result = await db.execute(select(Script).order_by(Script.stage))
    return [_script_dict(s) for s in result.scalars().all()]


@router.post("/{script_id}/activate")
async def activate_script(
    script_id: uuid.UUID,
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
