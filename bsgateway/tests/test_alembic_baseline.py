"""Unit tests for the Alembic baseline migration (Sprint 3 / S3-5).

These tests do NOT require a live database — they assert the structural
shape of ``alembic/versions/0001_baseline_schema.py`` against the legacy
raw-SQL files so regressions are caught at PR time. The full
schema-parity check (fresh PG with raw SQL ↔ ``alembic upgrade head``)
lives in ``scripts/verify_alembic_parity.sh`` and is run before stamping
prod (Lockin decision #3).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_BASELINE = REPO_ROOT / "alembic" / "versions" / "0001_baseline_schema.py"
SQL_DIRS = [
    REPO_ROOT / "bsgateway" / "routing" / "sql",
    REPO_ROOT / "bsgateway" / "executor" / "sql",
]


def _load_baseline_text() -> str:
    return ALEMBIC_BASELINE.read_text()


def _legacy_schema_files() -> list[Path]:
    schemas: list[Path] = []
    for d in SQL_DIRS:
        schemas.extend(sorted(d.glob("*schema.sql")))
    return schemas


# ---------------------------------------------------------------------------
# File presence / Alembic config sanity
# ---------------------------------------------------------------------------


class TestAlembicLayout:
    def test_alembic_ini_exists(self) -> None:
        assert (REPO_ROOT / "alembic.ini").is_file()

    def test_env_py_exists(self) -> None:
        assert (REPO_ROOT / "alembic" / "env.py").is_file()

    def test_baseline_revision_exists(self) -> None:
        assert ALEMBIC_BASELINE.is_file()

    def test_baseline_has_upgrade_and_downgrade(self) -> None:
        text = _load_baseline_text()
        assert "def upgrade()" in text
        assert "def downgrade()" in text

    def test_baseline_revision_id_pinned(self) -> None:
        """0001_baseline is the documented revision id (Lockin doc + PR)."""
        text = _load_baseline_text()
        assert re.search(r'^revision: str = "0001_baseline"', text, re.MULTILINE)

    def test_down_revision_is_none(self) -> None:
        text = _load_baseline_text()
        assert "down_revision: str | Sequence[str] | None = None" in text


# ---------------------------------------------------------------------------
# Every legacy table must appear in the baseline migration
# ---------------------------------------------------------------------------

EXPECTED_TABLES = [
    "routing_logs",
    "tenants",
    "tenant_models",
    "routing_rules",
    "rule_conditions",
    "tenant_intents",
    "intent_examples",
    "routing_feedback",
    "audit_logs",
    "api_keys",
    "workers",
    "executor_tasks",
]


@pytest.mark.parametrize("table", EXPECTED_TABLES)
def test_baseline_creates_table(table: str) -> None:
    text = _load_baseline_text()
    # Either inside a CREATE TABLE block or referenced by an ALTER on the
    # baseline path is fine; we just want every legacy table present.
    assert re.search(rf"CREATE TABLE IF NOT EXISTS {re.escape(table)}\b", text), (
        f"baseline migration is missing CREATE TABLE for {table}"
    )


@pytest.mark.parametrize("table", EXPECTED_TABLES)
def test_baseline_drops_table_on_downgrade(table: str) -> None:
    text = _load_baseline_text()
    assert f"DROP TABLE IF EXISTS {table}" in text, (
        f"baseline downgrade does not DROP {table} (round-trip test will fail)"
    )


# ---------------------------------------------------------------------------
# Tenant-isolating FK clauses must survive the rewrite
# ---------------------------------------------------------------------------

TENANT_FK_TABLES = [
    "tenant_models",
    "routing_rules",
    "tenant_intents",
    "routing_feedback",
    "audit_logs",
    "api_keys",
]


@pytest.mark.parametrize("table", TENANT_FK_TABLES)
def test_baseline_preserves_tenant_fk(table: str) -> None:
    """Sprint 0/1/2 isolation principle: every tenant-scoped table must
    reference tenants(id) — and the cascade-delete clause is what cleans
    up tenant data on tenant deletion. Drop a clause and you leak rows."""
    text = _load_baseline_text()
    # Locate the CREATE TABLE block for this table (regex spans newlines
    # because PG DDL is multi-line) and assert the cascade clause is
    # present inside it.
    block_match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {re.escape(table)}\b.*?\)$",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert block_match, f"CREATE TABLE block for {table} missing from baseline"
    block = block_match.group(0)
    assert "REFERENCES tenants(id) ON DELETE CASCADE" in block, (
        f"{table} lost its ON DELETE CASCADE clause — tenant deletion will leak rows"
    )


# ---------------------------------------------------------------------------
# Indexes that are load-bearing for Sprint 2 perf must still be created
# ---------------------------------------------------------------------------

EXPECTED_INDEXES = [
    "idx_routing_logs_tier",
    "idx_routing_logs_timestamp",
    "idx_routing_logs_tenant",
    "idx_routing_logs_tenant_time",  # Sprint 2 / M4
    "idx_routing_logs_rule_id",
    "idx_tenant_models_tenant",
    "idx_rules_tenant_priority",
    "idx_conditions_rule",
    "idx_intents_tenant",
    "idx_examples_intent",
    "idx_feedback_tenant",
    "idx_feedback_routing",
    "idx_audit_tenant_time",
    "idx_api_keys_tenant",
    "idx_api_keys_prefix",
    "idx_api_keys_tenant_created",  # Sprint 2 / M4 (api_keys composite)
    "idx_workers_tenant",
    "idx_workers_token",
    "idx_executor_tasks_tenant",
    "idx_executor_tasks_status",
]


@pytest.mark.parametrize("idx", EXPECTED_INDEXES)
def test_baseline_creates_index(idx: str) -> None:
    text = _load_baseline_text()
    assert re.search(rf"CREATE INDEX IF NOT EXISTS {re.escape(idx)}\b", text), (
        f"baseline migration is missing CREATE INDEX for {idx} — Sprint 2 perf regression risk"
    )


# ---------------------------------------------------------------------------
# Lockin decision #2 (legacy SHA-256 hash purge) must be replicated
# ---------------------------------------------------------------------------


def test_baseline_includes_legacy_hash_purge() -> None:
    """apikey_schema.sql performs a one-shot DELETE of pre-PBKDF2 hashes
    (lockin decision #2). Replay against staging snapshots must reproduce
    that cleanup or the security gain disappears."""
    text = _load_baseline_text()
    assert "DELETE FROM api_keys WHERE key_hash NOT LIKE 'pbkdf2_%'" in text


# ---------------------------------------------------------------------------
# Cross-check: every CREATE TABLE name in legacy SQL is also in baseline
# ---------------------------------------------------------------------------


def _extract_create_table_names(text: str) -> set[str]:
    return set(
        re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", text)
        + re.findall(r"CREATE TABLE (\w+)", text)
    )


def test_baseline_table_set_matches_legacy_sql() -> None:
    legacy_tables: set[str] = set()
    for f in _legacy_schema_files():
        legacy_tables |= _extract_create_table_names(f.read_text())

    baseline_tables = _extract_create_table_names(_load_baseline_text())

    missing = legacy_tables - baseline_tables
    assert not missing, (
        f"baseline migration is missing tables present in legacy SQL: {sorted(missing)}"
    )
