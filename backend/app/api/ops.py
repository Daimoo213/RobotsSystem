"""Operational endpoints that execute only configured, auditable actions."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.core.security import require

router = APIRouter(prefix="/ops", tags=["ops"])


def _not_configured(operation: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"{operation} is not configured for this deployment",
    )


@router.post("/backup")
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

