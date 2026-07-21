"""权限校验 + JWT认证 (PM和O&M两级角色)。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.models import User


class Role(str, Enum):
    PM = "pm"
    OM = "om"


# 密码哈希
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT 配置
JWT_SECRET = settings.jwt_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user: User) -> str:
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
        "ver": user.auth_version,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# 操作权限矩阵
ROLE_PERMISSIONS: dict[str, set[Role]] = {
    "device.command": {Role.OM},
    "device.command.estop": {Role.PM, Role.OM},
    "device.command.reset": {Role.OM},
    "device.command.pause": {Role.OM},
    "device.command.resume": {Role.OM},
    "estop.trigger": {Role.PM, Role.OM},
    "estop.recover": {Role.OM},
    "ops.backup": {Role.OM},
    "alert.acknowledge": {Role.OM},
    "task.create": {Role.PM},
    "task.update": {Role.PM},
    "task.reassign": {Role.PM},
    "task.pause": {Role.PM},
    "task.resume": {Role.PM},
    "script.activate": {Role.PM},
    "report.export": {Role.PM, Role.OM},
    "map.read": {Role.PM, Role.OM},
    "map.manage": {Role.OM},
    "read": {Role.PM, Role.OM},
    "user.manage": {Role.OM},
}


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve an operator only from the Authorization bearer token."""
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="未提供认证token")

    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="token无效或已过期")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if payload.get("ver") != user.auth_version:
        raise HTTPException(status_code=401, detail="token已失效，请重新登录")

    return user


def require(operation: str):
    """FastAPI 依赖工厂：要求调用者有 operation 权限。"""

    async def _checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        role = Role(current_user.role)
        allowed = ROLE_PERMISSIONS.get(operation, set())
        if role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"角色 '{role.value}' 无权执行 '{operation}'",
            )
        return current_user

    return _checker
