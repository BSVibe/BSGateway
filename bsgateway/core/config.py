"""BSGateway settings.

Phase A Batch 5: extends :class:`bsvibe_fastapi.FastApiSettings` so the
CORS / CSV-list / structlog plumbing matches the four-product baseline
(BSupervisor PR #13 §M18). BSGateway-specific knobs (gateway YAML
path, encryption key, BSupervisor service-account credentials, …)
remain on this subclass.

The legacy ``cors_allowed_origins: str`` field is replaced by the
shared ``Annotated[list[str], NoDecode]`` shape inherited from
:class:`FastApiSettings`. Existing deployments that ship
``CORS_ALLOWED_ORIGINS=http://a,http://b`` keep working unchanged.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import structlog
from bsvibe_fastapi import FastApiSettings
from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

_config_logger = structlog.get_logger(__name__)


class Settings(FastApiSettings):
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

    # Auth (BSVibe-Auth)
    bsvibe_auth_url: str = "https://auth.bsvibe.dev"
    encryption_key: str = ""  # 32-byte hex string for AES-256-GCM

    # ----------------------------------------------------------------------
    # OAuth2 client_credentials grant — see BSVibe-Auth `/api/oauth/token`.
    # Each backend has a dedicated row in `oauth_clients`; the secret is
    # provisioned once and stored in Vaultwarden.
    # ----------------------------------------------------------------------
    bsvibe_client_id: str = ""
    bsvibe_client_secret: str = ""

    # ----------------------------------------------------------------------
    # Phase 1 token-cutover — bsvibe-authz 3-way dispatch.
    # `bootstrap_token` is the raw `bsv_admin_*` value; on read of
    # `bootstrap_token_hash` (the canonical input the dispatcher sees),
    # the SHA-256 digest is derived in-memory. Production may set
    # `BOOTSTRAP_TOKEN_HASH` directly to keep the raw value out of
    # process memory; that pre-hashed value wins. The introspection
    # fields mirror :class:`bsvibe_authz.Settings` so a single ``.env``
    # configures both classes.
    # ----------------------------------------------------------------------
    bootstrap_token: str = ""
    bootstrap_token_hash: str = ""
    introspection_url: str = ""
    introspection_client_id: str = ""
    introspection_client_secret: str = ""

    # ----------------------------------------------------------------------
    # User-JWT verification — fed straight into bsvibe_authz.Settings.
    # ``user_jwt_jwks_url`` (preferred for prod, ES256/RS256 with key
    # rotation), ``user_jwt_public_key`` (static PEM), or ``user_jwt_secret``
    # (HS256 dev fallback). When unset the user-JWT verification path is
    # disabled and only bootstrap / opaque / PAT-JWT-introspection tokens
    # are accepted.
    # ----------------------------------------------------------------------
    user_jwt_jwks_url: str = ""
    user_jwt_public_key: str = ""
    user_jwt_secret: str = ""
    user_jwt_algorithm: str = "ES256"
    user_jwt_audience: str = "authenticated"
    user_jwt_issuer: str = ""

    # ----------------------------------------------------------------------
    # Phase 0 P0.7 — BSupervisor preflight integration.
    # ----------------------------------------------------------------------
    bsupervisor_url: str = ""
    bsupervisor_audit_enabled: bool = False
    bsupervisor_audit_timeout_ms: int = 200
    # "open" → fail-open (default, matches BSNexus's pre-cutover behaviour);
    # "closed" → block runs when BSupervisor is unreachable.
    bsupervisor_audit_fail_mode: str = "open"

    # ----------------------------------------------------------------------
    # Phase Audit Batch 2 — bsvibe-audit outbox emission.
    # ----------------------------------------------------------------------
    # Enables the SQLAlchemy-side ``audit_outbox`` writer + relay. Default
    # **on** so the four ``gateway.*`` events surface in the BSVibe-Auth
    # audit log out of the box. Set ``BSVIBE_AUDIT_OUTBOX_ENABLED=false``
    # to opt out (the only failure path is a missing
    # ``COLLECTOR_DATABASE_URL``, which keeps the relay disabled even
    # when this flag is true — see ``audit_publisher.build_audit_outbox``).
    #
    # Operator action when upgrading: run ``alembic upgrade head`` (creates
    # the ``audit_outbox`` table from rev ``0002_audit_outbox``) and set
    # ``BSVIBE_AUTH_AUDIT_URL`` so the relay has somewhere to push events.
    bsvibe_audit_outbox_enabled: bool = True

    # Frontend dist directory (for serving dashboard static files)
    frontend_dist_dir: str = ""

    # FastApiSettings.cors_allowed_origins is Annotated[list[str], NoDecode]
    # with a CSV field_validator. Override the default to "" → [] (legacy
    # behaviour: when unset, fall back to localhost in app.create_app).
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _derive_bootstrap_hash(self) -> Settings:
        if not self.bootstrap_token_hash and self.bootstrap_token:
            self.bootstrap_token_hash = hashlib.sha256(self.bootstrap_token.encode()).hexdigest()
        return self

    @property
    def encryption_key_bytes(self) -> bytes:
        """Return the encryption key as raw bytes.

        Raises RuntimeError if ENCRYPTION_KEY is not set — provider API keys
        require encryption and must not be stored in plaintext.
        """
        if not self.encryption_key:
            raise RuntimeError(
                "ENCRYPTION_KEY is required — provider API keys cannot be "
                "stored without encryption. Generate one with: "
                'python -c "import os; print(os.urandom(32).hex())"'
            )
        try:
            key = bytes.fromhex(self.encryption_key)
        except ValueError as e:
            raise ValueError("ENCRYPTION_KEY must be a valid 64-character hex string") from e
        if len(key) != 32:
            raise ValueError("ENCRYPTION_KEY must be exactly 64 hex characters (32 bytes)")
        return key


settings = Settings()
