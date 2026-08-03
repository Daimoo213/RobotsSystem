"""Operational endpoints that execute only configured, auditable actions."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis import CHANNEL_EVENTS, redis
from app.core.security import require
from app.models.models import Project

router = APIRouter(prefix="/ops", tags=["ops"])


class MappingModeRequest(BaseModel):
    enabled: bool = Field(description="是否允许外部建图网关上传并替换当前完整点云地图")


def _active_project(db: AsyncSession):
    return select(Project).where(Project.is_active.is_(True)).order_by(Project.created_at.desc()).limit(1)


@router.get(
    "/mapping",
    summary="查询建图模式开关",
    description="读取当前项目的建图模式。关闭时，设备网关的完整点云地图上传接口会拒绝写入。",
    response_description="建图模式状态和当前项目标识",
)
async def get_mapping_mode(db: AsyncSession = Depends(get_db), _role=Depends(require("read"))) -> dict:
    project = await db.scalar(_active_project(db))
    return {
        "configured": project is not None,
        "enabled": bool(project and project.mapping_enabled),
        "project_code": project.code if project else None,
    }


@router.patch(
    "/mapping",
    summary="切换建图模式开关",
    description="仅 O&M 运维角色可以切换建图模式；开启后外部建图网关才可上传完整点云地图。",
    response_description="更新后的建图模式状态",
)
async def set_mapping_mode(
    req: MappingModeRequest = Body(description="建图模式开关设置"),
    db: AsyncSession = Depends(get_db),
    _role=Depends(require("ops.mapping")),
) -> dict:
    project = await db.scalar(_active_project(db))
    if project is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目尚未初始化，不能设置建图模式")
    project.mapping_enabled = req.enabled
    await db.flush()
    payload = {
        "type": "mapping_mode_changed",
        "enabled": project.mapping_enabled,
        "project_code": project.code,
        "message": f"建图模式已{'开启' if project.mapping_enabled else '关闭'}",
    }
    await redis().publish(CHANNEL_EVENTS, json.dumps({"channel": CHANNEL_EVENTS, "data": payload}))
    return {"ok": True, **payload}


def _not_configured(operation: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"{operation} is not configured for this deployment",
    )


@router.post(
    "/backup",
    summary="创建数据库备份",
    description="使用部署时显式配置的 pg_dump 生成 PostgreSQL custom-format 备份；未配置时返回 501。",
    response_description="备份文件名、字节大小和创建时间。",
)
async def backup(_role=Depends(require("ops.backup"))) -> dict:
    """Create a PostgreSQL custom-format backup only when configured explicitly."""

    if not settings.backup_directory or not settings.pg_dump_path:
        _not_configured("database backup")
    dump_path = Path(settings.pg_dump_path)
    if not dump_path.is_file():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="configured pg_dump executable was not found")
    target_dir = Path(settings.backup_directory).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = target_dir / f"robots_scheduler_{timestamp}.dump"
    environment = {**os.environ, "PGPASSWORD": settings.pg_password}
    process = await asyncio.create_subprocess_exec(
        str(dump_path),
        "--format=custom",
        "--file", str(output_path),
        "--host", settings.pg_host,
        "--port", str(settings.pg_port),
        "--username", settings.pg_user,
        settings.pg_db,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await process.communicate()
    if process.returncode != 0:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"pg_dump failed: {stderr.decode('utf-8', errors='replace').strip()}")
    return {
        "ok": True,
        "backup_file": output_path.name,
        "size_bytes": output_path.stat().st_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
