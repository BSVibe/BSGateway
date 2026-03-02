from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """BSGateway configuration via environment variables."""

    gateway_config_path: Path = Path("gateway.yaml")
    database_url: str | None = None
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
