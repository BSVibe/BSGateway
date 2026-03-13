from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def encryption_key_bytes(self) -> bytes:
        """Return the encryption key as raw bytes."""
        if not self.encryption_key:
            return b""
        return bytes.fromhex(self.encryption_key)


settings = Settings()
