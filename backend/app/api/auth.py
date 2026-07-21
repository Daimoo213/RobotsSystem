"""Authentication, one-time project setup, and operator account management."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import Role, create_access_token, get_current_user, hash_password, require, verify_password
from app.models.models import Project, User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    role: str
    display_name: str
    username: str


class InitialUser(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=12, max_length=128)


class InitialSetupRequest(BaseModel):
    project_code: str = Field(min_length=1, max_length=32)
    project_name: str = Field(min_length=1, max_length=128)
    location: str | None = Field(default=None, max_length=256)
    map_frame: str = Field(default="map", min_length=1, max_length=64)
    timezone: str = Field(default="Asia/Hong_Kong", min_length=1, max_length=64)
    om: InitialUser
    pm: InitialUser


class UserCreate(InitialUser):
    role: Role


@router.get("/setup-status")
async def setup_status(db: AsyncSession = Depends(get_db)) -> dict:
    return {"initialized": bool(await db.scalar(select(func.count(User.id))))}


@router.post("/setup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def initial_setup(
    req: InitialSetupRequest,
    x_initial_setup_token: str | None = Header(default=None),
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


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(req: UserCreate, db: AsyncSession = Depends(get_db), _role=Depends(require("user.manage"))) -> dict:
    if await db.scalar(select(User).where(User.username == req.username)):
        raise HTTPException(status_code=409, detail="username already exists")
    user = User(username=req.username, display_name=req.display_name, password_hash=hash_password(req.password), role=req.role.value)
    db.add(user)
    await db.flush()
    return {"id": str(user.id), "username": user.username, "display_name": user.display_name, "role": user.role}


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    user = await db.scalar(select(User).where(User.username == req.username))
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")
    return LoginResponse(token=create_access_token(user), role=user.role, display_name=user.display_name, username=user.username)


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)) -> dict:
    return {"id": str(current_user.id), "username": current_user.username, "role": current_user.role, "display_name": current_user.display_name}


@router.get("/roles")
async def roles() -> list[dict]:
    return [{"value": Role.PM.value, "label": "PM"}, {"value": Role.OM.value, "label": "O&M"}]
