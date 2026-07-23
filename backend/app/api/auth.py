"""Authentication, one-time project setup, and operator account management."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import Role, create_access_token, get_current_user, hash_password, require, verify_password
from app.models.models import Project, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(description="操作员登录名。")
    password: str = Field(description="操作员密码；仅用于本次登录，不会以明文保存。")


class LoginResponse(BaseModel):
    token: str = Field(description="后续操作员接口使用的 Bearer JWT。")
    role: str = Field(description="操作员角色，当前为 pm 或 om。")
    display_name: str = Field(description="操作员显示名称。")
    username: str = Field(description="操作员登录名。")


class InitialUser(BaseModel):
    username: str = Field(min_length=3, max_length=64, description="初始操作员登录名，长度为 3 至 64 个字符。")
    display_name: str = Field(min_length=1, max_length=64, description="初始操作员显示名称。")
    password: str = Field(min_length=12, max_length=128, description="初始操作员密码，长度为 12 至 128 个字符。")


class InitialSetupRequest(BaseModel):
    project_code: str = Field(min_length=1, max_length=32, description="现场项目唯一编码。")
    project_name: str = Field(min_length=1, max_length=128, description="现场项目名称。")
    location: str | None = Field(default=None, max_length=256, description="项目所在地或现场地址。")
    map_frame: str = Field(default="map", min_length=1, max_length=64, description="机器人、点位和地图统一使用的坐标系名称。")
    timezone: str = Field(default="Asia/Hong_Kong", min_length=1, max_length=64, description="项目 IANA 时区名称，用于业务时间展示。")
    om: InitialUser = Field(description="首个 O&M 运维管理员账号。")
    pm: InitialUser = Field(description="首个 PM 项目管理员账号。")


class UserCreate(InitialUser):
    role: Role = Field(description="新账号角色：pm 为项目管理，om 为设备运维。")


@router.get(
    "/setup-status",
    summary="查询系统初始化状态",
    description="检查数据库中是否已经存在操作员账号，用于决定前端显示初始化页还是登录页。",
    response_description="initialized 为 true 表示系统已完成首次初始化。",
)
async def setup_status(db: AsyncSession = Depends(get_db)) -> dict:
    return {"initialized": bool(await db.scalar(select(func.count(User.id))))}


@router.post(
    "/setup",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
    summary="执行首次项目初始化",
    description="仅允许在系统尚无账号时调用一次，同时创建真实项目、首个 O&M 账号和首个 PM 账号。",
    response_description="初始化成功后返回 O&M 账号的登录令牌和身份信息。",
)
async def initial_setup(
    req: InitialSetupRequest = Body(description="项目资料及首批 O&M、PM 账号。"),
    x_initial_setup_token: str | None = Header(default=None, description="部署环境配置的一次性初始化令牌。"),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Create the first real project and the PM/O&M accounts exactly once."""

    if not settings.initial_setup_token or not x_initial_setup_token or not secrets.compare_digest(x_initial_setup_token, settings.initial_setup_token):
        raise HTTPException(status_code=401, detail="invalid initial setup token")
    if await db.scalar(select(func.count(User.id))):
        raise HTTPException(status_code=409, detail="system has already been initialized")
    project = Project(
        code=req.project_code,
        name=req.project_name,
        location=req.location,
        map_frame=req.map_frame,
        timezone=req.timezone,
        is_active=True,
    )
    om = User(username=req.om.username, display_name=req.om.display_name, password_hash=hash_password(req.om.password), role=Role.OM.value)
    pm = User(username=req.pm.username, display_name=req.pm.display_name, password_hash=hash_password(req.pm.password), role=Role.PM.value)
    db.add_all([project, om, pm])
    await db.flush()
    return LoginResponse(token=create_access_token(om), role=om.role, display_name=om.display_name, username=om.username)


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    summary="创建操作员账号",
    description="由具有账号管理权限的 O&M 操作员创建新的 PM 或 O&M 账号。",
    response_description="新账号的数据库 ID、登录名、显示名称和角色。",
)
async def create_user(req: UserCreate = Body(description="新操作员账号资料。"), db: AsyncSession = Depends(get_db), _role=Depends(require("user.manage"))) -> dict:
    if await db.scalar(select(User).where(User.username == req.username)):
        raise HTTPException(status_code=409, detail="username already exists")
    user = User(username=req.username, display_name=req.display_name, password_hash=hash_password(req.password), role=req.role.value)
    db.add(user)
    await db.flush()
    return {"id": str(user.id), "username": user.username, "display_name": user.display_name, "role": user.role}


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="操作员登录",
    description="校验本地账号密码并签发有效期受配置控制的 Bearer JWT。",
    response_description="登录令牌、角色和操作员基本信息。",
)
async def login(req: LoginRequest = Body(description="操作员登录凭据。"), db: AsyncSession = Depends(get_db)) -> LoginResponse:
    user = await db.scalar(select(User).where(User.username == req.username))
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")
    return LoginResponse(token=create_access_token(user), role=user.role, display_name=user.display_name, username=user.username)


@router.get(
    "/me",
    summary="查询当前操作员",
    description="根据 Bearer JWT 返回当前登录账号；已失效或版本不匹配的令牌会被拒绝。",
    response_description="当前操作员 ID、登录名、显示名称和角色。",
)
async def me(current_user: User = Depends(get_current_user)) -> dict:
    return {"id": str(current_user.id), "username": current_user.username, "role": current_user.role, "display_name": current_user.display_name}


@router.get(
    "/roles",
    summary="查询可用操作员角色",
    description="返回初始化和账号管理界面可选择的 PM、O&M 角色。",
    response_description="角色值和显示标签列表。",
)
async def roles() -> list[dict]:
    return [{"value": Role.PM.value, "label": "PM"}, {"value": Role.OM.value, "label": "O&M"}]
