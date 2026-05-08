"""Demo data seeding for a single ephemeral tenant.

Called by ``DemoSessionService.create_session`` after the new tenant row
is inserted. Populates realistic demo content so the visitor's dashboard
renders immediately:

- 4 tenant_models (gpt-4o-mini, claude-haiku, claude-sonnet, local-llama)
- 5 routing rules with proper conditions + 1 default fallback
- 30 routing log entries spanning the past 7 days (multiple models)
- 3 tenant intents with example utterances

All inserts are scoped to ``tenant_id`` so they cascade-delete via the
existing FK ``ON DELETE CASCADE`` chain when the GC reaps the tenant.
"""

from __future__ import annotations

import json
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

# (name, priority, target_model, is_default, conditions[])
# conditions: list of (condition_type, field, operator, value, negate)
# Lower priority = matched first. is_default=True is the catch-all,
# evaluated only when no other rule matches.
DEMO_RULES: list[tuple[str, int, str, bool, list[tuple[str, str, str, object, bool]]]] = [
    (
        "emergency-bypass",
        5,
        "claude-sonnet",
        False,
        # Only matches when the request explicitly opts in via X-Urgent header
        # → emergency-bypass NEVER fires for ordinary demo requests.
        [("text_pattern", "user_text", "regex", r"\b(URGENT|CRITICAL|emergency)\b", False)],
    ),
    (
        "code-tasks-to-claude",
        20,
        "claude-sonnet",
        False,
        [("intent", "classified_intent", "eq", "code-generation", False)],
    ),
    (
        "classification-to-local",
        30,
        "local-llama",
        False,
        [("intent", "classified_intent", "eq", "classification", False)],
    ),
    (
        "short-prompts-to-mini",
        50,
        "gpt-4o-mini",
        False,
        [("token_count", "estimated_tokens", "lt", 200, False)],
    ),
    (
        "default-fallback",
        100,
        "claude-haiku",
        True,  # default rule — only used when nothing else matches
        [],
    ),
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
    # ─── Models (tenant_models) ───────────────────────────────────────────
    # Without these, the Models page is empty and the routing engine has
    # nothing to dispatch to except whatever fallback the prod resolver
    # picks up — visitor sees "No models" + every routing test falls
    # through to a single rule.
    for model_name, provider, litellm_model in DEMO_MODELS:
        await conn.execute(
            """
            INSERT INTO tenant_models (id, tenant_id, model_name, provider,
                                       litellm_model, is_active, extra_params)
            VALUES ($1, $2, $3, $4, $5, TRUE, '{}'::jsonb)
            ON CONFLICT (tenant_id, model_name) DO NOTHING
            """,
            uuid4(),
            tenant_id,
            model_name,
            provider,
            litellm_model,
        )

    # ─── Routing rules + their conditions ─────────────────────────────────
    # Without conditions, _match_rule returns True (empty AND-loop) for
    # every rule, so the lowest-priority rule wins unconditionally — that
    # is why the demo previously bounced everything to "emergency-bypass".
    for name, priority, target_model, is_default, conditions in DEMO_RULES:
        rule_id = uuid4()
        await conn.execute(
            """
            INSERT INTO routing_rules (id, tenant_id, name, priority,
                                       target_model, is_active, is_default)
            VALUES ($1, $2, $3, $4, $5, TRUE, $6)
            """,
            rule_id,
            tenant_id,
            name,
            priority,
            target_model,
            is_default,
        )
        for cond_type, field, op, value, negate in conditions:
            await conn.execute(
                """
                INSERT INTO rule_conditions (id, rule_id, condition_type,
                                             operator, field, value, negate)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                """,
                uuid4(),
                rule_id,
                cond_type,
                op,
                field,
                json.dumps(value),
                negate,
            )

    # ─── Routing logs (last 7 days, ~30 entries spread across models) ─────
    # Schema columns: timestamp, user_text, system_prompt, token_count,
    # tier (NOT NULL), strategy (NOT NULL), score, original_model (NOT NULL),
    # resolved_model (NOT NULL), tenant_id. id is autoincrement integer.
    now = datetime.now(UTC)
    for i in range(30):
        _model_name, _provider, resolved = DEMO_MODELS[i % len(DEMO_MODELS)]
        ts = now - timedelta(days=i // 5, hours=i * 2)
        token_count = 150 + (i % 11) * 30
        await conn.execute(
            """
            INSERT INTO routing_logs (timestamp, user_text, system_prompt,
                                      token_count, tier, strategy, score,
                                      original_model, resolved_model, tenant_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            ts,
            f"Demo request {i + 1}",
            "",
            token_count,
            ["fast", "balanced", "premium"][i % 3],
            "static",
            int(10 + (i % 9) * 10),
            "auto",
            resolved,
            tenant_id,
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
        models=len(DEMO_MODELS),
        rules=len(DEMO_RULES),
        routing_logs=30,
        intents=len(DEMO_INTENTS),
    )
