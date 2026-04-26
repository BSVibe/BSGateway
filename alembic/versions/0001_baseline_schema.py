"""baseline schema (Sprint 3 / S3-5 — initial Alembic adoption)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-25

This migration captures the union of every raw SQL schema previously
applied by :mod:`bsgateway.core.migrate`:

* ``routing/sql/schema.sql``        — ``routing_logs`` + indexes
* ``routing/sql/tenant_schema.sql`` — ``tenants``, ``tenant_models``,
  ALTER routing_logs (tenant_id, rule_id) + their indexes
* ``routing/sql/rules_schema.sql``  — ``routing_rules``,
  ``rule_conditions``, ``tenant_intents``, ``intent_examples``
* ``routing/sql/feedback_schema.sql`` — ``routing_feedback``
* ``routing/sql/audit_schema.sql``    — ``audit_logs``
* ``routing/sql/apikey_schema.sql``   — ``api_keys`` + index hygiene +
  PBKDF2 lockin DELETE (no-op on a fresh DB; preserved for replay
  fidelity against staging snapshots)
* ``executor/sql/executor_schema.sql`` — ``workers``, ``executor_tasks``

Lockin decision #3 (BSVibe Execution Lockin §3) governs deployment:

* **staging**: ``alembic upgrade head`` — no data, runs every statement.
* **prod**: one ``alembic stamp head`` (on the existing schema), then
  every subsequent migration via ``alembic upgrade head``.

The implementation uses ``op.execute`` with the original DDL text
verbatim (``CREATE TABLE IF NOT EXISTS``, ``ALTER TABLE … IF NOT EXISTS``,
``CREATE INDEX IF NOT EXISTS``) so a fresh PG and a stamped prod DB
converge on byte-identical schema. **Schema diff vs the legacy raw-SQL
path: 0** — verified by ``scripts/verify_alembic_parity.sh`` (live PG
round-trip) and the structural assertions in
``bsgateway/tests/test_alembic_baseline.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# routing_logs — base table
# ---------------------------------------------------------------------------

ROUTING_LOGS_DDL = """
CREATE TABLE IF NOT EXISTS routing_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_text TEXT NOT NULL,
    system_prompt TEXT DEFAULT '',
    token_count INTEGER,
    conversation_turns INTEGER,
    code_block_count INTEGER,
    code_lines INTEGER,
    has_error_trace BOOLEAN,
    tool_count INTEGER,
    tier TEXT NOT NULL,
    strategy TEXT NOT NULL,
    score INTEGER,
    original_model TEXT NOT NULL,
    resolved_model TEXT NOT NULL,
    embedding BYTEA,
    nexus_task_type TEXT,
    nexus_priority TEXT,
    nexus_complexity_hint INTEGER,
    decision_source TEXT
)
"""

ROUTING_LOGS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_routing_logs_tier ON routing_logs(tier)",
    "CREATE INDEX IF NOT EXISTS idx_routing_logs_timestamp ON routing_logs(timestamp)",
]

# Legacy migration backfill (raw-SQL schema.sql appended these even
# though the columns are already declared above). Replicated verbatim so
# replay against an old DB is a no-op (IF NOT EXISTS) and a fresh apply
# stays idempotent.
ROUTING_LOGS_BACKFILL_ALTERS = [
    "ALTER TABLE routing_logs ADD COLUMN IF NOT EXISTS nexus_task_type TEXT",
    "ALTER TABLE routing_logs ADD COLUMN IF NOT EXISTS nexus_priority TEXT",
    "ALTER TABLE routing_logs ADD COLUMN IF NOT EXISTS nexus_complexity_hint INTEGER",
    "ALTER TABLE routing_logs ADD COLUMN IF NOT EXISTS decision_source TEXT",
]


# ---------------------------------------------------------------------------
# tenants + tenant_models, then attach tenant_id / rule_id to routing_logs
# ---------------------------------------------------------------------------

TENANTS_DDL = """
CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    settings JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

TENANT_MODELS_DDL = """
CREATE TABLE IF NOT EXISTS tenant_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    litellm_model TEXT NOT NULL,
    api_key_encrypted TEXT,
    api_base TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    extra_params JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, model_name)
)
"""

TENANT_LINK_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_tenant_models_tenant ON tenant_models(tenant_id)",
    "ALTER TABLE routing_logs ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id)",
    "ALTER TABLE routing_logs ADD COLUMN IF NOT EXISTS rule_id UUID",
    "CREATE INDEX IF NOT EXISTS idx_routing_logs_tenant ON routing_logs(tenant_id)",
    (
        "CREATE INDEX IF NOT EXISTS idx_routing_logs_tenant_time "
        "ON routing_logs(tenant_id, timestamp DESC)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_routing_logs_rule_id ON routing_logs(rule_id)",
]


# ---------------------------------------------------------------------------
# routing_rules + rule_conditions + tenant_intents + intent_examples
# ---------------------------------------------------------------------------

RULES_DDL = """
CREATE TABLE IF NOT EXISTS routing_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    target_model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, name),
    UNIQUE(tenant_id, priority) DEFERRABLE INITIALLY DEFERRED
)
"""

RULE_CONDITIONS_DDL = """
CREATE TABLE IF NOT EXISTS rule_conditions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id UUID NOT NULL REFERENCES routing_rules(id) ON DELETE CASCADE,
    condition_type TEXT NOT NULL,
    operator TEXT NOT NULL DEFAULT 'eq',
    field TEXT NOT NULL,
    value JSONB NOT NULL,
    negate BOOLEAN NOT NULL DEFAULT FALSE
)
"""

TENANT_INTENTS_DDL = """
CREATE TABLE IF NOT EXISTS tenant_intents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    threshold REAL NOT NULL DEFAULT 0.7,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, name)
)
"""

INTENT_EXAMPLES_DDL = """
CREATE TABLE IF NOT EXISTS intent_examples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_id UUID NOT NULL REFERENCES tenant_intents(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    embedding BYTEA,
    embedding_model TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

RULES_INDEXES_AND_BACKFILL = [
    ("CREATE INDEX IF NOT EXISTS idx_rules_tenant_priority ON routing_rules(tenant_id, priority)"),
    "CREATE INDEX IF NOT EXISTS idx_conditions_rule ON rule_conditions(rule_id)",
    "CREATE INDEX IF NOT EXISTS idx_intents_tenant ON tenant_intents(tenant_id)",
    # Mirrors the historical ALTER in rules_schema.sql so replay against an
    # old prod DB lacking embedding_model adds the column.
    "ALTER TABLE intent_examples ADD COLUMN IF NOT EXISTS embedding_model TEXT",
    "CREATE INDEX IF NOT EXISTS idx_examples_intent ON intent_examples(intent_id)",
]


# ---------------------------------------------------------------------------
# routing_feedback
# ---------------------------------------------------------------------------

FEEDBACK_DDL = """
CREATE TABLE IF NOT EXISTS routing_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    routing_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

FEEDBACK_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_feedback_tenant ON routing_feedback(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_routing ON routing_feedback(routing_id)",
]


# ---------------------------------------------------------------------------
# audit_logs
# ---------------------------------------------------------------------------

AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    actor TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

AUDIT_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_logs(tenant_id, created_at DESC)",
]


# ---------------------------------------------------------------------------
# api_keys
# ---------------------------------------------------------------------------

APIKEYS_DDL = """
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    scopes JSONB NOT NULL DEFAULT '["chat"]',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

# Replicates apikey_schema.sql line-for-line so DBs at every history
# point converge on the same schema after upgrade head.
APIKEYS_HYGIENE = [
    "ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_key_hash_key",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix)",
    (
        "CREATE INDEX IF NOT EXISTS idx_api_keys_tenant_created "
        "ON api_keys(tenant_id, created_at DESC)"
    ),
    "DROP INDEX IF EXISTS idx_api_keys_hash",
    # Lockin decision #2: purge legacy unsalted SHA-256 hashes. DELETE on
    # a fresh DB is a no-op; preserved here so prod stamping reproduces
    # the cleanup that the raw schema.sql performed.
    "DELETE FROM api_keys WHERE key_hash NOT LIKE 'pbkdf2_%'",
]


# ---------------------------------------------------------------------------
# workers + executor_tasks
# ---------------------------------------------------------------------------

WORKERS_DDL = """
CREATE TABLE IF NOT EXISTS workers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    labels JSONB DEFAULT '[]'::jsonb,
    capabilities JSONB DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'offline',
    last_heartbeat TIMESTAMPTZ,
    token_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

EXECUTOR_TASKS_DDL = """
CREATE TABLE IF NOT EXISTS executor_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    executor_type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    worker_id UUID REFERENCES workers(id),
    output TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

EXECUTOR_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_workers_tenant ON workers(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_workers_token ON workers(token_hash)",
    "CREATE INDEX IF NOT EXISTS idx_executor_tasks_tenant ON executor_tasks(tenant_id)",
    ("CREATE INDEX IF NOT EXISTS idx_executor_tasks_status ON executor_tasks(tenant_id, status)"),
]


def upgrade() -> None:
    """Apply the union of every legacy raw-SQL schema as a single revision.

    Order matches :func:`bsgateway.core.migrate.run_migrations`:
    routing_logs → tenants/tenant_models → rules → feedback → audit →
    apikeys → executor. The dependency order is load-bearing because
    several tables FK back to ``tenants`` and ``tenant_models``, and
    ``executor_tasks.worker_id`` FKs ``workers.id``.
    """
    op.execute(ROUTING_LOGS_DDL)
    for stmt in ROUTING_LOGS_INDEXES:
        op.execute(stmt)
    for stmt in ROUTING_LOGS_BACKFILL_ALTERS:
        op.execute(stmt)

    op.execute(TENANTS_DDL)
    op.execute(TENANT_MODELS_DDL)
    for stmt in TENANT_LINK_DDL:
        op.execute(stmt)

    op.execute(RULES_DDL)
    op.execute(RULE_CONDITIONS_DDL)
    op.execute(TENANT_INTENTS_DDL)
    op.execute(INTENT_EXAMPLES_DDL)
    for stmt in RULES_INDEXES_AND_BACKFILL:
        op.execute(stmt)

    op.execute(FEEDBACK_DDL)
    for stmt in FEEDBACK_INDEXES:
        op.execute(stmt)

    op.execute(AUDIT_DDL)
    for stmt in AUDIT_INDEXES:
        op.execute(stmt)

    op.execute(APIKEYS_DDL)
    for stmt in APIKEYS_HYGIENE:
        op.execute(stmt)

    op.execute(WORKERS_DDL)
    op.execute(EXECUTOR_TASKS_DDL)
    for stmt in EXECUTOR_INDEXES:
        op.execute(stmt)


def downgrade() -> None:
    """Drop every table created by :func:`upgrade`.

    Order is the reverse of upgrade — children before parents — and uses
    ``DROP … IF EXISTS CASCADE`` so a partial baseline (e.g. a stamped
    prod DB that hasn't yet had executor tables) downgrades without
    error. **DDL only — no data backfill** (Sprint 3 / S3-5 constraint).

    NOTE: prod will never run ``alembic downgrade`` against the baseline
    revision (Lockin decision #3 = stamp head once, never go below it).
    The downgrade exists for staging and the alembic round-trip test
    (``upgrade head → downgrade -1 → upgrade head``).
    """
    # executor → apikeys → audit → feedback → rules → tenants → routing_logs
    op.execute("DROP TABLE IF EXISTS executor_tasks CASCADE")
    op.execute("DROP TABLE IF EXISTS workers CASCADE")
    op.execute("DROP TABLE IF EXISTS api_keys CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS routing_feedback CASCADE")
    op.execute("DROP TABLE IF EXISTS intent_examples CASCADE")
    op.execute("DROP TABLE IF EXISTS tenant_intents CASCADE")
    op.execute("DROP TABLE IF EXISTS rule_conditions CASCADE")
    op.execute("DROP TABLE IF EXISTS routing_rules CASCADE")
    op.execute("DROP TABLE IF EXISTS tenant_models CASCADE")
    op.execute("DROP TABLE IF EXISTS tenants CASCADE")
    op.execute("DROP TABLE IF EXISTS routing_logs CASCADE")
