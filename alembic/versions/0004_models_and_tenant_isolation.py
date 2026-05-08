"""Phase 3 / TASK-002 — per-tenant ``models`` table + tighten
``routing_logs.tenant_id`` to NOT NULL.

Revision ID: 0004_models_and_tenant_isolation
Revises: 0003_drop_api_keys
Create Date: 2026-05-08

Phase 3 of the BSVibe AI-Native Control Plane introduces the yaml-union-DB
model registry: ``gateway.yaml`` provides operator-managed system models
and a new per-tenant ``models`` table layers custom additions and
``hide_system`` overrides on top. The merge contract is implemented by
``ModelRegistryService`` (TASK-003) and consumed by the routing hook
(TASK-004) and the admin REST surface (TASK-005).

This migration also closes the last gap in the tenant-isolation
invariant: ``routing_logs.tenant_id`` was attached as nullable in
``0001_baseline`` (it was retro-fitted onto the legacy global table).
Phase 3 locks the column to NOT NULL using the safe multi-step pattern
called out in the project rules — purge any pre-Phase-3 NULL rows
**first**, then ALTER … SET NOT NULL — so a production upgrade can
never fail mid-deploy on the constraint flip.

Design notes:

* ``origin`` is constrained to ``{custom, hide_system}`` via a CHECK so
  the merge layer can dispatch on a single column (``custom`` rows are
  tenant additions; ``hide_system`` rows blank a yaml entry by name).
* ``litellm_model`` / ``litellm_params`` are nullable because the
  ``hide_system`` shape carries no litellm payload — the row exists
  only to subtract a name from the yaml set.
* ``UNIQUE(tenant_id, name)`` matches the ``tenant_models`` shape (each
  tenant owns its own namespace; the same name across tenants is fine).
* ``ON DELETE CASCADE`` on the FK so tenant deletion cleans up models
  the same way it cleans every other tenant-scoped table.
* ``idx_models_tenant`` is the per-tenant lookup hot path — every
  ``ModelRegistryService.list_models(tenant_id)`` call hits this index.

Round-trip parity (``upgrade head → downgrade -1 → upgrade head``) is
preserved — downgrade drops the table and relaxes the NOT NULL back to
the ``0001_baseline`` shape.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_models_and_tenant_isolation"
down_revision: str | Sequence[str] | None = "0003_drop_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# models — per-tenant overrides + hide_system rows for the yaml-union-DB merge
# ---------------------------------------------------------------------------

MODELS_DDL = """
CREATE TABLE IF NOT EXISTS models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('custom', 'hide_system')),
    litellm_model TEXT,
    litellm_params JSONB,
    is_passthrough BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, name)
)
"""

MODELS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_models_tenant ON models(tenant_id)",
]


# ---------------------------------------------------------------------------
# routing_logs — tighten tenant_id from nullable → NOT NULL (multi-step)
# ---------------------------------------------------------------------------

# Multi-step pattern: PG aborts SET NOT NULL on the first NULL it
# encounters, so the DELETE pass MUST execute before the ALTER.
ROUTING_LOGS_BACKFILL_PURGE = "DELETE FROM routing_logs WHERE tenant_id IS NULL"
ROUTING_LOGS_TENANT_SET_NOT_NULL = "ALTER TABLE routing_logs ALTER COLUMN tenant_id SET NOT NULL"
ROUTING_LOGS_TENANT_DROP_NOT_NULL = "ALTER TABLE routing_logs ALTER COLUMN tenant_id DROP NOT NULL"


def upgrade() -> None:
    """Create ``models`` and tighten ``routing_logs.tenant_id`` to NOT NULL.

    Order is load-bearing:

    1. Create the ``models`` table + index. No data dependency on the
       routing_logs alter, but PG fails fast on a missing FK target so
       running this first keeps the failure mode obvious.
    2. Purge legacy NULL-tenant ``routing_logs`` rows. These are
       pre-Phase-3 observability data with no tenant context — they
       have no home in a tenant-isolated world.
    3. ``ALTER COLUMN … SET NOT NULL`` on the now-clean column.
    """
    op.execute(MODELS_DDL)
    for stmt in MODELS_INDEXES:
        op.execute(stmt)

    op.execute(ROUTING_LOGS_BACKFILL_PURGE)
    op.execute(ROUTING_LOGS_TENANT_SET_NOT_NULL)


def downgrade() -> None:
    """Reverse :func:`upgrade` for round-trip parity.

    The downgrade does NOT restore deleted ``routing_logs`` rows — the
    Sprint 3 / S3-5 rule is "DDL only, no data backfill" on downgrade.
    Re-applying the upgrade on the same DB is a no-op for the DELETE
    (no NULL rows remain) and idempotent for the ALTER.
    """
    op.execute(ROUTING_LOGS_TENANT_DROP_NOT_NULL)
    op.execute("DROP TABLE IF EXISTS models CASCADE")
