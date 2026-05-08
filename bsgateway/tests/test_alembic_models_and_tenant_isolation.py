"""Phase 3 / TASK-002 — Alembic ``0004_models_and_tenant_isolation`` revision.

The Phase 3 plan adds the per-tenant ``models`` table (yaml-union-DB merge for
the model registry) and tightens ``routing_logs.tenant_id`` from
nullable → NOT NULL so the tenant-isolation invariant stretches across
the observability path too. This file pins the structural shape so a
regression is caught at PR time:

* revision id ``0004_models_and_tenant_isolation`` chained off
  ``0003_drop_api_keys``
* ``upgrade()`` creates ``models`` (UUID pk, tenant_id NOT NULL FK
  with ON DELETE CASCADE, UNIQUE(tenant_id, name), origin CHECK clause,
  is_passthrough default TRUE, created_at + updated_at, idx_models_tenant)
* ``upgrade()`` backfills ``routing_logs`` (purges NULL tenant_id rows
  so the SET NOT NULL pass cannot fail mid-deploy) and tightens the
  column to NOT NULL
* ``downgrade()`` drops the ``models`` table and relaxes
  ``routing_logs.tenant_id`` back to nullable so the round-trip
  (``upgrade head → downgrade -1 → upgrade head``) ends in the same
  structural shape as a fresh forward apply

Live PG round-trip lives in ``scripts/verify_alembic_parity.sh``; this
file is the no-DB structural gate.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_VERSIONS = REPO_ROOT / "alembic" / "versions"
REVISION_FILE = ALEMBIC_VERSIONS / "0004_models_and_tenant_isolation.py"


def _load_text() -> str:
    return REVISION_FILE.read_text()


class TestModelsAndTenantIsolationRevision:
    def test_revision_file_exists(self) -> None:
        assert REVISION_FILE.is_file(), (
            "0004_models_and_tenant_isolation.py is missing — Phase 3 plan "
            "requires a dedicated revision so prod can `alembic upgrade head` "
            "to onboard the per-tenant models table without manual SQL."
        )

    def test_revision_id_pinned(self) -> None:
        assert re.search(
            r'^revision: str = "0004_models_and_tenant_isolation"',
            _load_text(),
            re.MULTILINE,
        )

    def test_chained_to_0003_drop_api_keys(self) -> None:
        assert re.search(
            r'^down_revision: .*= "0003_drop_api_keys"',
            _load_text(),
            re.MULTILINE,
        ), "0004 must chain off 0003 so prod stamp + upgrade flow stays linear"

    def test_upgrade_and_downgrade_present(self) -> None:
        text = _load_text()
        assert "def upgrade()" in text
        assert "def downgrade()" in text


class TestModelsTableShape:
    """The ``models`` table is the per-tenant half of the yaml-union-DB merge.

    Every column / constraint asserted here is load-bearing for the
    ``ModelRegistryService`` contract spelled out in TASK-003.
    """

    def test_create_table_models(self) -> None:
        assert re.search(r"CREATE TABLE IF NOT EXISTS models\b", _load_text()), (
            "upgrade() must CREATE the models table"
        )

    def test_models_id_is_uuid_primary_key(self) -> None:
        text = _load_text()
        block = _models_create_block(text)
        assert re.search(
            r"id\s+UUID\s+PRIMARY KEY\s+DEFAULT\s+gen_random_uuid\(\)",
            block,
            re.IGNORECASE,
        ), "models.id must be UUID PRIMARY KEY DEFAULT gen_random_uuid()"

    def test_models_tenant_id_not_null_with_cascade_fk(self) -> None:
        block = _models_create_block(_load_text())
        # tenant-isolation invariant: NOT NULL FK + ON DELETE CASCADE so
        # tenant deletion can't leak rows.
        assert re.search(
            r"tenant_id\s+UUID\s+NOT NULL\s+REFERENCES\s+tenants\(id\)\s+ON DELETE CASCADE",
            block,
            re.IGNORECASE,
        ), "models.tenant_id must be NOT NULL FK to tenants(id) ON DELETE CASCADE"

    def test_models_name_not_null(self) -> None:
        block = _models_create_block(_load_text())
        assert re.search(r"name\s+TEXT\s+NOT NULL", block, re.IGNORECASE)

    def test_models_origin_with_check_clause(self) -> None:
        block = _models_create_block(_load_text())
        # CHECK clause restricts origin to 'custom' or 'hide_system'.
        assert re.search(r"origin\s+TEXT\s+NOT NULL", block, re.IGNORECASE), (
            "models.origin must be NOT NULL TEXT"
        )
        assert re.search(
            r"CHECK\s*\(\s*origin\s+IN\s*\(\s*'custom'\s*,\s*'hide_system'\s*\)\s*\)",
            block,
            re.IGNORECASE,
        ), "models.origin must enforce the {custom, hide_system} CHECK domain"

    def test_models_litellm_columns_nullable(self) -> None:
        block = _models_create_block(_load_text())
        assert re.search(r"litellm_model\s+TEXT\b", block, re.IGNORECASE)
        assert re.search(r"litellm_params\s+JSONB\b", block, re.IGNORECASE)
        # NULL is fine for hide_system rows — the column carries no
        # litellm payload in that case.
        assert "litellm_model TEXT NOT NULL" not in block
        assert "litellm_params JSONB NOT NULL" not in block

    def test_models_is_passthrough_defaults_true(self) -> None:
        block = _models_create_block(_load_text())
        assert re.search(
            r"is_passthrough\s+BOOLEAN\s+NOT NULL\s+DEFAULT\s+TRUE",
            block,
            re.IGNORECASE,
        ), "models.is_passthrough must default to TRUE"

    def test_models_timestamps(self) -> None:
        block = _models_create_block(_load_text())
        assert re.search(
            r"created_at\s+TIMESTAMPTZ\s+NOT NULL\s+DEFAULT\s+NOW\(\)",
            block,
            re.IGNORECASE,
        )
        assert re.search(
            r"updated_at\s+TIMESTAMPTZ\s+NOT NULL\s+DEFAULT\s+NOW\(\)",
            block,
            re.IGNORECASE,
        )

    def test_models_unique_tenant_name(self) -> None:
        block = _models_create_block(_load_text())
        assert re.search(r"UNIQUE\s*\(\s*tenant_id\s*,\s*name\s*\)", block, re.IGNORECASE), (
            "models must enforce UNIQUE(tenant_id, name)"
        )

    def test_models_tenant_index(self) -> None:
        assert re.search(
            r"CREATE INDEX IF NOT EXISTS idx_models_tenant\s+ON\s+models\(tenant_id\)",
            _load_text(),
            re.IGNORECASE,
        ), "models must have idx_models_tenant for the per-tenant lookup hot path"

    def test_downgrade_drops_models(self) -> None:
        text = _load_text()
        assert re.search(r"DROP TABLE IF EXISTS models", text), (
            "downgrade() must DROP the models table for round-trip parity"
        )


class TestRoutingLogsTenantTightening:
    """``routing_logs.tenant_id`` was nullable in 0001_baseline. Phase 3
    locks the tenant-isolation invariant by tightening it to NOT NULL —
    using the safe multi-step pattern (backfill → SET NOT NULL) so a
    production upgrade can never fail halfway."""

    def test_upgrade_backfills_null_tenant_rows_first(self) -> None:
        """Rows with NULL tenant_id are pre-Phase-3 observability data
        with no tenant context. The upgrade must purge them BEFORE the
        SET NOT NULL alter or PG will reject the constraint change."""
        text = _load_text()
        assert re.search(
            r"DELETE FROM routing_logs\s+WHERE\s+tenant_id IS NULL",
            text,
            re.IGNORECASE,
        ), (
            "upgrade() must DELETE legacy NULL-tenant rows before SET NOT NULL "
            "(safe multi-step pattern from feedback_alembic_phantom_revision)."
        )

    def test_upgrade_sets_routing_logs_tenant_not_null(self) -> None:
        text = _load_text()
        assert re.search(
            r"ALTER TABLE routing_logs\s+ALTER COLUMN tenant_id\s+SET NOT NULL",
            text,
            re.IGNORECASE,
        ), "upgrade() must ALTER routing_logs.tenant_id SET NOT NULL"

    def test_upgrade_orders_delete_before_alter(self) -> None:
        """The DELETE backfill MUST execute before the SET NOT NULL alter
        — otherwise the alter aborts on existing NULL rows and the whole
        migration rolls back."""
        text = _load_text()
        delete_pos = text.lower().find("delete from routing_logs")
        alter_pos = text.lower().find("alter column tenant_id\n        set not null")
        if alter_pos == -1:
            alter_pos = text.lower().find("alter column tenant_id set not null")
        assert delete_pos != -1 and alter_pos != -1
        assert delete_pos < alter_pos, (
            "DELETE backfill must precede SET NOT NULL ALTER — otherwise the "
            "ALTER aborts on existing NULL rows"
        )

    def test_downgrade_relaxes_routing_logs_tenant_back_to_nullable(self) -> None:
        text = _load_text()
        assert re.search(
            r"ALTER TABLE routing_logs\s+ALTER COLUMN tenant_id\s+DROP NOT NULL",
            text,
            re.IGNORECASE,
        ), (
            "downgrade() must DROP NOT NULL on routing_logs.tenant_id so the "
            "round-trip ends in the 0001_baseline shape"
        )


def _models_create_block(text: str) -> str:
    """Return the body of the ``CREATE TABLE … models`` block."""
    match = re.search(
        r"CREATE TABLE IF NOT EXISTS models\b.*?\)\s*['\"]",
        text,
        re.DOTALL,
    )
    assert match, "CREATE TABLE block for models missing from migration"
    return match.group(0)
