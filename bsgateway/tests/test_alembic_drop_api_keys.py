"""Phase 1 token-cutover — Alembic ``0003_drop_api_keys`` revision.

The PR retires the self-hosted ``api_keys`` table; bsvibe-authz
introspection + bootstrap tokens take over. This test pins the
structural shape of the new revision so a regression is caught at PR
time:

* revision id ``0003_drop_api_keys`` chained off ``0002_audit_outbox``
* ``upgrade()`` drops the ``api_keys`` table (CASCADE so dependent
  indexes/constraints don't block on legacy stamped DBs)
* ``downgrade()`` re-creates the table + the indexes ``0001_baseline``
  built (so a round-trip ``upgrade head → downgrade -1 → upgrade head``
  stays clean against staging)

Live PG round-trip lives in ``scripts/verify_alembic_parity.sh``; this
file is the no-DB structural gate.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_VERSIONS = REPO_ROOT / "alembic" / "versions"
DROP_REVISION = ALEMBIC_VERSIONS / "0003_drop_api_keys.py"


def _load_text() -> str:
    return DROP_REVISION.read_text()


class TestDropApiKeysRevision:
    def test_revision_file_exists(self) -> None:
        assert DROP_REVISION.is_file(), (
            "0003_drop_api_keys.py is missing — Phase 1 token-cutover requires "
            "a dedicated revision so prod can `alembic upgrade head` to drop the "
            "retired table without manual SQL."
        )

    def test_revision_id_pinned(self) -> None:
        assert re.search(r'^revision: str = "0003_drop_api_keys"', _load_text(), re.MULTILINE)

    def test_chained_to_0002_audit_outbox(self) -> None:
        assert re.search(r'^down_revision: .*= "0002_audit_outbox"', _load_text(), re.MULTILINE), (
            "0003 must chain off 0002 so prod stamp + upgrade flow stays linear"
        )

    def test_upgrade_drops_api_keys(self) -> None:
        text = _load_text()
        assert "def upgrade()" in text
        assert re.search(r"drop_table\(\s*['\"]api_keys['\"]", text) or re.search(
            r"DROP TABLE IF EXISTS api_keys", text
        ), "upgrade() must DROP the api_keys table"

    def test_downgrade_recreates_api_keys(self) -> None:
        text = _load_text()
        assert "def downgrade()" in text
        assert re.search(r"create_table\(\s*['\"]api_keys['\"]", text) or re.search(
            r"CREATE TABLE IF NOT EXISTS api_keys", text
        ), (
            "downgrade() must re-create api_keys so the upgrade→downgrade→upgrade "
            "round-trip is clean against staging snapshots"
        )

    def test_downgrade_recreates_baseline_indexes(self) -> None:
        """Round-trip parity: the indexes ``0001_baseline`` built must come
        back so a full ``downgrade -1 → upgrade head`` ends in the same
        structural shape as a fresh ``upgrade head``."""
        text = _load_text()
        for idx in (
            "idx_api_keys_tenant",
            "idx_api_keys_prefix",
            "idx_api_keys_tenant_created",
        ):
            assert idx in text, f"downgrade() must re-create the {idx} index for round-trip parity"
