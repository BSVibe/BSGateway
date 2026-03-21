from __future__ import annotations

from pathlib import Path

import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict

_config_logger = structlog.get_logger(__name__)


class Settings(BaseSettings):
    """BSGateway configuration via environment variables."""

    gateway_config_path: Path = Path("gateway.yaml")
    collector_database_url: str | None = None
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""
    log_level: str = "INFO"

    # API server
    api_port: int = 8000
    api_host: str = "0.0.0.0"

    # Auth
    jwt_secret: str = ""
    encryption_key: str = ""  # 32-byte hex string for AES-256-GCM

    # Superadmin bootstrap key (for creating first tenant)
    superadmin_key: str = ""

    # CORS (comma-separated list of allowed origins, e.g. "http://localhost:5173,https://app.example.com")
    cors_allowed_origins: str = ""

    # Frontend dist directory (for serving dashboard static files)
    frontend_dist_dir: str = ""

    # Development seed data (creates test tenant + API key on startup)
    seed_dev_data: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def encryption_key_bytes(self) -> bytes:
        """Return the encryption key as raw bytes."""
        if not self.encryption_key:
            _config_logger.warning(
                "encryption_key_not_set",
                hint="provider API keys will not be encrypted",
            )
            return b""
        try:
            key = bytes.fromhex(self.encryption_key)
        except ValueError as e:
            raise ValueError(
                "ENCRYPTION_KEY must be a valid 64-character hex string"
            ) from e
        if len(key) != 32:
            raise ValueError(
                "ENCRYPTION_KEY must be exactly 64 hex characters (32 bytes)"
            )
        return key


settings = Settings()
