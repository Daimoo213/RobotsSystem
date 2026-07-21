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
        description="机器人集群智能调度系统 API",
        version=settings.app_version,
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
    from app.api import alerts, auth, cameras, dashboard, devices, map as map_api, pointcloud, reports, scripts, tasks
    from app.api import ops as ops_api
    from app.api import estop as estop_api
    from app.ws import ws_router

    api_prefix = settings.api_prefix
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(dashboard.router, prefix=api_prefix)
    app.include_router(devices.router, prefix=api_prefix)
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
    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.app_version,
        }

    @app.get("/ready", response_model=None)
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
