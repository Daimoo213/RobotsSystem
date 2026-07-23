"""Emergency stop router — trigger / recover."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.security import require
from app.services.runtime import get_runtime

router = APIRouter(prefix="/estop", tags=["estop"])


@router.post(
    "",
    summary="触发全局急停",
    description="锁存全局急停，并为所有启用的设备网关排入高优先级 estop 命令。机端硬件急停仍为最终安全边界。",
    response_description="急停已激活的状态和触发角色。",
)
async def trigger_estop(_role=Depends(require("estop.trigger"))) -> dict:
    """Trigger global emergency stop (PM or O&M)."""
    runtime = get_runtime()
    await runtime.trigger_estop(source=_role.role.value)
    return {"ok": True, "active": True, "source": _role.role.value}


@router.delete(
    "",
    summary="申请解除全局急停",
    description="仅 O&M 可解除平台急停锁存，并向所有设备排入 release 命令；设备仍须自行确认物理安全条件。",
    response_description="平台急停锁存已解除的状态。",
)
async def recover_estop(_role=Depends(require("estop.recover"))) -> dict:
    """Recover from emergency stop (O&M only)."""
    runtime = get_runtime()
    await runtime.recover_estop()
    return {"ok": True, "active": False}
