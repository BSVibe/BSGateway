"""Demo data seeding for a single ephemeral tenant.

Called by ``DemoSessionService.create_session`` after the new tenant row
is inserted. Populates realistic demo content so the visitor's dashboard
renders immediately:

- 3 API keys (2 active, 1 revoked)
- 5 routing rules across different priorities
- 30 routing log entries spanning the past 7 days (multiple models)
- 3 tenant intents with example utterances
- 1 routing decision recently made

All inserts are scoped to ``tenant_id`` so they cascade-delete via the
existing FK ``ON DELETE CASCADE`` chain when the GC reaps the tenant.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import structlog

logger = structlog.get_logger(__name__)

DEMO_MODELS = [
    ("gpt-4o-mini", "openai", "openai/gpt-4o-mini"),
    ("claude-haiku", "anthropic", "anthropic/claude-haiku-4-5-20251001"),
    ("claude-sonnet", "anthropic", "anthropic/claude-sonnet-4-5-20251001"),
    ("local-llama", "ollama", "ollama_chat/llama3.2"),
]

DEMO_RULES = [
    ("prefer-cheap-for-simple", 10, "complexity_static < 0.3", "gpt-4o-mini"),
    ("code-tasks-to-claude", 20, "intent = 'code'", "claude-sonnet"),
    ("local-for-classification", 30, "intent = 'classification'", "local-llama"),
    ("default-fallback", 100, "true", "claude-haiku"),
    ("emergency-bypass", 5, "metadata.urgent = true", "claude-sonnet"),
]

DEMO_INTENTS = [
    ("code-generation", "Generate or modify source code"),
    ("classification", "Classify text into a fixed category"),
    ("summary", "Summarize a long document"),
]


async def seed_demo(*, tenant_id: UUID, conn: asyncpg.Connection) -> None:
    """Populate demo data for ``tenant_id``. Idempotent within the same connection.

    All operations are within the caller's transaction (DemoSessionService
    wraps create_session in conn.transaction()).
    """
    # ─── API keys ──────────────────────────────────────────────────────────
    # Three keys: two active (one prod-like, one dev-like), one revoked.
    api_keys = [
        ("Production", True, "demo_prod_"),
        ("Development", True, "demo_dev_"),
        ("Legacy (revoked)", False, "demo_old_"),
    ]
    for name, is_active, prefix in api_keys:
        # key_hash is a random opaque value (visitor never sees the plaintext;
        # they're shown the masked dashboard view)
        await conn.execute(
            """
            INSERT INTO api_keys (id, tenant_id, name, key_hash, key_prefix,
                                  scopes, is_active)
            VALUES ($1, $2, $3, $4, $5, '["chat"]'::jsonb, $6)
            """,
            uuid4(),
            tenant_id,
            name,
            secrets.token_hex(32),
            prefix + secrets.token_hex(4),
            is_active,
        )

    # ─── Routing rules ─────────────────────────────────────────────────────
    for name, priority, _condition_text, target_model in DEMO_RULES:
        rule_id = uuid4()
        await conn.execute(
            """
            INSERT INTO routing_rules (id, tenant_id, name, priority,
                                       target_model, is_active)
            VALUES ($1, $2, $3, $4, $5, TRUE)
            """,
            rule_id,
            tenant_id,
            name,
            priority,
            target_model,
        )

    # ─── Routing logs (last 7 days, ~30 entries spread across models) ─────
    now = datetime.now(UTC)
    for i in range(30):
        _model_name, _provider, resolved = DEMO_MODELS[i % len(DEMO_MODELS)]
        ts = now - timedelta(days=i // 5, hours=i * 2)
        await conn.execute(
            """
            INSERT INTO routing_logs (id, tenant_id, requested_model,
                                      resolved_model, complexity_score,
                                      latency_ms, prompt_tokens,
                                      completion_tokens, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT DO NOTHING
            """,
            uuid4(),
            tenant_id,
            "auto",
            resolved,
            0.1 + (i % 9) * 0.1,
            120 + (i % 13) * 50,
            150 + (i % 11) * 30,
            80 + (i % 7) * 25,
            ts,
        )

    # ─── Tenant intents ────────────────────────────────────────────────────
    for name, description in DEMO_INTENTS:
        await conn.execute(
            """
            INSERT INTO tenant_intents (id, tenant_id, name, description)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (tenant_id, name) DO NOTHING
            """,
            uuid4(),
            tenant_id,
            name,
            description,
        )

    logger.info(
        "demo_seed_complete",
        tenant_id=str(tenant_id),
        api_keys=len(api_keys),
        rules=len(DEMO_RULES),
        routing_logs=30,
        intents=len(DEMO_INTENTS),
    )
