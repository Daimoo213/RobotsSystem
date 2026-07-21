"""Application configuration using pydantic-settings."""

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────
    app_name: str = "RobotsClusterScheduler"
    app_version: str = "dev"
    debug: bool = False
    jwt_secret: str = ""
    initial_setup_token: str = ""
    api_prefix: str = "/api"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:3000",
        ]
    )

    # HTTP device gateway. Required in every environment.
    device_gateway_api_key: str | None = None
    gateway_heartbeat_ttl_seconds: int = 5
    gateway_offline_after_seconds: int = 15
    gateway_telemetry_future_tolerance_seconds: int = 30
    gateway_command_delivery_timeout_seconds: int = 10

    # ── Database (PostgreSQL + TimescaleDB) ──────────────
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "scheduler"
    pg_password: str = "scheduler123"
    pg_db: str = "scheduler"
    pg_echo: bool = False

    # ── Redis ────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    # ── Scheduler ────────────────────────────────────────
    scheduler_tick_interval: float = 1.0  # seconds
    scheduler_speed_factor: float = 1.0

    # ── Device Adapter ───────────────────────────────────

    # ── Point Cloud ──────────────────────────────────────

    # ── Energy ───────────────────────────────────────────
    low_battery_threshold: float = 20.0  # percent
    charging_threshold: float = 90.0  # stop charging at
    maintenance_runtime_hours_threshold: float | None = None
    maintenance_mileage_km_threshold: float | None = None

    # ── Safety ───────────────────────────────────────────
    device_safety_distance: float = 2.0  # meters, collision lock trigger
    localization_warning_drift_meters: float = 0.3
    localization_forced_calibration_drift_meters: float = 0.5
    localization_correction_min_interval_seconds: int = 10

    # PostgreSQL backup is deliberately opt-in. Set both values in the deployed
    # environment to expose the operator-triggered backup endpoint.
    backup_directory: str | None = None
    pg_dump_path: str | None = None

    # ── MQTT (optional, for real devices) ────────────────

    @model_validator(mode="after")
    def validate_deployment_secrets(self) -> "Settings":
        """Reject missing, placeholder, reused, or weak production secrets."""

        if self.debug:
            return self
        required = {
            "jwt_secret": self.jwt_secret,
            "device_gateway_api_key": self.device_gateway_api_key or "",
            "initial_setup_token": self.initial_setup_token,
            "pg_password": self.pg_password,
            "redis_password": self.redis_password or "",
        }
        invalid: list[str] = []
        for name, value in required.items():
            normalized = value.strip().lower()
            minimum = 16 if name in {"pg_password", "redis_password"} else 24
            if (
                len(value) < minimum
                or normalized.startswith("replace-with-")
                or normalized in {"changeme", "change-me", "password", "secret", "scheduler123"}
                or normalized.startswith("<")
            ):
                invalid.append(name)
        if invalid:
            raise ValueError("invalid production secrets: " + ", ".join(invalid))
        if len(set(required.values())) != len(required):
            raise ValueError("production secrets must all be different")
        return self

    @property
    def pg_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    @property
    def pg_sync_dsn(self) -> str:
        """Sync DSN for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
