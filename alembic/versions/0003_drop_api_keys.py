"""Phase 1 token cutover — drop the retired ``api_keys`` table.

Revision ID: 0003_drop_api_keys
Revises: 0002_audit_outbox
Create Date: 2026-05-08

Removes the self-hosted ``api_keys`` table introduced in
``0001_baseline``. As of the BSVibe Phase 1 token cutover (decisions
2026-05-07) authentication runs through bsvibe-authz with RFC 7662
introspection of opaque bearer tokens (``bsv_sk_*``). The table,
repository, service, and router that backed the old self-hosted flow
are deleted in the same PR.

Lockin decision #3 still applies — prod is stamped at ``head``, then
``alembic upgrade head`` runs forward. The CASCADE on ``DROP TABLE`` is
load-bearing because legacy stamped DBs may carry indexes/constraints
that ``0001_baseline`` introduced; any of those would otherwise block
the drop.

Downgrade re-creates the table and the indexes ``0001_baseline`` built,
so the staging round-trip (``upgrade head → downgrade -1 → upgrade
head``) ends in the same structural shape as a fresh forward apply.
**No data is restored** on downgrade — the table comes back empty,
matching the Sprint 3 / S3-5 "DDL only, no data backfill" rule.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_drop_api_keys"
down_revision: str | Sequence[str] | None = "0002_audit_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# DDL kept in module scope so the upgrade/downgrade pair can be read
# top-down without scrolling through inline strings.
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

APIKEYS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix)",
    (
        "CREATE INDEX IF NOT EXISTS idx_api_keys_tenant_created "
        "ON api_keys(tenant_id, created_at DESC)"
    ),
]


def upgrade() -> None:
    """Drop the retired ``api_keys`` table."""
    op.execute("DROP TABLE IF EXISTS api_keys CASCADE")


def downgrade() -> None:
    """Re-create the ``api_keys`` table and its baseline indexes (DDL only)."""
    op.execute(APIKEYS_DDL)
    for stmt in APIKEYS_INDEXES:
        op.execute(stmt)
