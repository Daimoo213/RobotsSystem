"""Emergency stop router — trigger / recover."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import require
from app.services.runtime import get_runtime

router = APIRouter(prefix="/estop", tags=["estop"])


@router.post("")
async def trigger_estop(_role=Depends(require("estop.trigger"))) -> dict:
    """Trigger global emergency stop (PM or O&M)."""
    runtime = get_runtime()
    await runtime.trigger_estop(source=_role.role.value)
    return {"ok": True, "active": True, "source": _role.role.value}


@router.delete("")
async def recover_estop(_role=Depends(require("estop.recover"))) -> dict:
    """Recover from emergency stop (O&M only)."""
    runtime = get_runtime()
    await runtime.recover_estop()
    return {"ok": True, "active": False}
