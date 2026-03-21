"""Development seed data — creates a test tenant, API key, and sample models.

Only runs when SEED_DEV_DATA=true. Idempotent (skips if tenant slug exists).
"""

from __future__ import annotations

import asyncpg
import structlog

from bsgateway.core.security import encrypt_value, generate_api_key, hash_api_key
from bsgateway.tenant.repository import TenantRepository

logger = structlog.get_logger(__name__)

DEV_TENANT_SLUG = "dev-team"
DEV_TENANT_NAME = "Dev Team"


async def seed_dev_data(pool: asyncpg.Pool, encryption_key: bytes) -> None:
    """Seed development data if it doesn't already exist."""
    repo = TenantRepository(pool)

    # Check if already seeded
    existing = await repo.get_tenant_by_slug(DEV_TENANT_SLUG)
    if existing:
        logger.info("seed_skipped", reason="tenant already exists", slug=DEV_TENANT_SLUG)
        return

    # Generate a random API key (logged once to console)
    dev_api_key, key_prefix = generate_api_key()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Create tenant
            tenant = await conn.fetchrow(
                """
                INSERT INTO tenants (name, slug, settings)
                VALUES ($1, $2, $3)
                RETURNING *
                """,
                DEV_TENANT_NAME,
                DEV_TENANT_SLUG,
                '{"rate_limit": {"requests_per_minute": 60}}',
            )
            tenant_id = tenant["id"]

            # 2. Create API key (random, shown in logs once)
            key_hash = hash_api_key(dev_api_key)
            await conn.execute(
                """
                INSERT INTO tenant_api_keys (tenant_id, key_hash, key_prefix, name, scopes)
                VALUES ($1, $2, $3, $4, $5)
                """,
                tenant_id,
                key_hash,
                key_prefix,
                "dev-default",
                ["chat", "admin"],
            )

            # 3. Create sample models (no real API keys — use dummy encrypted values)
            models = [
                ("gpt-4o-mini", "openai", "openai/gpt-4o-mini"),
                ("gpt-4o", "openai", "openai/gpt-4o"),
                ("claude-sonnet", "anthropic", "anthropic/claude-sonnet-4-20250514"),
            ]
            for model_name, provider, litellm_model in models:
                encrypted_key = None
                if encryption_key:
                    encrypted_key = encrypt_value("sk-dev-placeholder", encryption_key)
                await conn.execute(
                    """
                    INSERT INTO tenant_models
                        (tenant_id, model_name, provider, litellm_model, api_key_encrypted)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    tenant_id,
                    model_name,
                    provider,
                    litellm_model,
                    encrypted_key,
                )

            # 4. Create a default routing rule (route everything to gpt-4o-mini)
            await conn.execute(
                """
                INSERT INTO routing_rules (tenant_id, name, priority, is_default, target_model)
                VALUES ($1, $2, $3, $4, $5)
                """,
                tenant_id,
                "default-to-mini",
                100,
                True,
                "gpt-4o-mini",
            )

    logger.info(
        "seed_completed",
        tenant_id=str(tenant_id),
        slug=DEV_TENANT_SLUG,
        api_key_prefix=key_prefix,
        models=[m[0] for m in models],
    )
    logger.info(
        "seed_dev_api_key_created",
        hint="Save this key now — it will not be shown again",
        api_key_prefix=key_prefix,
    )
