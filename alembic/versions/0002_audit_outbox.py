"""Phase Audit Batch 2 — bsvibe-audit ``audit_outbox`` table.

Revision ID: 0002_audit_outbox
Revises: 0001_baseline
Create Date: 2026-04-26

Adds the outbox table that ``bsvibe_audit.AuditEmitter`` writes into and
``bsvibe_audit.OutboxRelay`` drains. The DDL mirrors
``bsvibe_audit.outbox.schema.AuditOutboxRecord`` byte-for-byte — the
package owns the wire shape and we re-state it here so a single
``alembic upgrade head`` brings up the table on a fresh PG without
``register_audit_outbox_with`` ever touching production at runtime.

Why not autogenerate? BSGateway intentionally keeps
``target_metadata = None`` (alembic/env.py) — the migrations are written
by hand to mirror the legacy raw-SQL schema. We follow the same
convention here so the BSupervisor / BSage / BSNexus migration set stays
consistent across the four products.

Idempotent up: matches Lockin §3 #3 (byte-identical replay against
stamped prod DBs). Drop on downgrade is unconditional — operators can
``alembic downgrade -1`` to roll back the audit table without touching
the rest of the schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_audit_outbox"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the ``audit_outbox`` table mirroring AuditOutboxRecord."""
    op.create_table(
        "audit_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), nullable=False, unique=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "dead_letter",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_audit_outbox_undelivered",
        "audit_outbox",
        ["delivered_at", "next_attempt_at"],
    )


def downgrade() -> None:
    """Drop the ``audit_outbox`` table (and its index)."""
    op.drop_index("ix_audit_outbox_undelivered", table_name="audit_outbox")
    op.drop_table("audit_outbox")
