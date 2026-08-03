"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.logging import get_logger, setup_logging
from app.core.redis import close_redis, init_redis, redis


OPENAPI_TAGS = [
    {"name": "auth", "description": "项目初始化、操作员登录、账号创建和身份查询。"},
    {"name": "dashboard", "description": "从 PostgreSQL 真实业务记录聚合的项目、进度、能耗、安全和运维看板数据。"},
    {"name": "devices", "description": "机器人设备注册、真实遥测、命令队列、校正记录和操作员控制。"},
    {"name": "cameras", "description": "摄像头及外部视觉服务的注册、检测结果上报和查询。"},
    {"name": "tasks", "description": "施工任务的创建、查询、修改、调度控制和设备改派。"},
    {"name": "scripts", "description": "项目施工阶段脚本的查询与激活。"},
    {"name": "map", "description": "项目区域、施工点位和外部地图资产的持久化管理。"},
    {"name": "alerts", "description": "真实设备和业务规则产生的告警查询与确认。"},
    {"name": "reports", "description": "基于数据库记录生成 Excel 或 PDF 报表。"},
    {"name": "pointcloud", "description": "接收外部 SLAM、传感器或 Gazebo 桥接程序提供的完整点云地图。"},
    {"name": "ops", "description": "需要显式部署配置和 O&M 权限的运维操作，包括建图模式开关。"},
    {"name": "estop", "description": "全局急停触发与安全恢复。设备本体安全回路始终具有更高优先级。"},
    {"name": "系统状态", "description": "供进程管理器和部署健康检查使用的存活与就绪接口。"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup + shutdown."""
    log = get_logger("app.lifespan")
    log.info("app.starting", app=settings.app_name, debug=settings.debug)

    # Redis
    await init_redis()
    log.info("redis.connected")

    # Start background services
    from app.services.runtime import RuntimeContext

    runtime = RuntimeContext(app)
    await runtime.start()
    app.state.runtime = runtime
    log.info("runtime.started")

    yield

    # Shutdown
    log.info("app.stopping")
    await runtime.stop()
    await close_redis()
    log.info("app.stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()
    log = get_logger("app.create")

    app = FastAPI(
        title="RobotsClusterScheduler",
        description=(
            "机器人集群智能调度系统 HTTP API。操作员接口使用登录返回的 Bearer JWT；"
            "设备接口使用 `X-Device-Gateway-Key`。设备命令采用至少一次投递，"
            "机器人或桥接程序必须按命令 ID 去重，并通过真实遥测确认动作结果。"
            "浏览器实时通道 `/ws` 使用 `jwt.<token>` WebSocket 子协议，详细消息格式见接入文档。"
        ),
        version=settings.app_version,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──────────────────────────────────────────
    from app.api import alerts, auth, cameras, dashboard, device_map, devices, map as map_api, pointcloud, reports, scripts, tasks
    from app.api import ops as ops_api
    from app.api import estop as estop_api
    from app.ws import ws_router

    api_prefix = settings.api_prefix
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(dashboard.router, prefix=api_prefix)
    app.include_router(devices.router, prefix=api_prefix)
    app.include_router(device_map.router, prefix=api_prefix)
    app.include_router(cameras.router, prefix=api_prefix)
    app.include_router(tasks.router, prefix=api_prefix)
    app.include_router(scripts.router, prefix=api_prefix)
    app.include_router(map_api.router, prefix=api_prefix)
    app.include_router(alerts.router, prefix=api_prefix)
    app.include_router(reports.router, prefix=api_prefix)
    app.include_router(pointcloud.router, prefix=api_prefix)
    app.include_router(ops_api.router, prefix=api_prefix)
    app.include_router(estop_api.router, prefix=api_prefix)

    # WebSocket
    app.include_router(ws_router)

    # Health check
    @app.get(
        "/health",
        tags=["系统状态"],
        summary="检查服务进程存活状态",
        description="仅确认 FastAPI 进程可以响应，不检查 PostgreSQL 或 Redis。",
        response_description="服务名称、版本和存活状态。",
    )
    async def health() -> dict:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.app_version,
        }

    @app.get(
        "/ready",
        response_model=None,
        tags=["系统状态"],
        summary="检查服务依赖就绪状态",
        description="分别检查 PostgreSQL 查询和 Redis PING；任一依赖不可用时返回 HTTP 503。",
        response_description="整体就绪状态以及 PostgreSQL、Redis 的逐项检查结果。",
    )
    async def ready() -> dict | JSONResponse:
        """Report readiness only while PostgreSQL and Redis are usable."""

        checks = {"postgres": False, "redis": False}
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            checks["postgres"] = True
        except Exception:
            pass
        try:
            checks["redis"] = bool(await redis().ping())
        except Exception:
            pass
        payload = {
            "status": "ready" if all(checks.values()) else "not_ready",
            "version": settings.app_version,
            "checks": checks,
        }
        if all(checks.values()):
            return payload
        return JSONResponse(status_code=503, content=payload)

    log.info("app.created", prefix=api_prefix)
    return app


app = create_app()
