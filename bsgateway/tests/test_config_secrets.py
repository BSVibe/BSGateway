"""Regression tests for S0-1 — vendor secrets and DB credentials must
be supplied via env vars only, with no hardcoded fallbacks shipping
in code or templates.

See `Docs/BSVibe_Ecosystem_Audit.md` §5.1 (C1) and
`Docs/BSVibe_Execution_Lockin.md` §7 for the underlying contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bsgateway.core.config import Settings


class TestEncryptionKeyRequired:
    def test_blank_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        s = Settings(encryption_key="")
        with pytest.raises(RuntimeError, match="ENCRYPTION_KEY is required"):
            _ = s.encryption_key_bytes

    def test_invalid_hex_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        s = Settings(encryption_key="not-hex" * 10)
        with pytest.raises(ValueError):
            _ = s.encryption_key_bytes

    def test_short_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
        s = Settings(encryption_key="aa" * 16)
        with pytest.raises(ValueError, match="64 hex characters"):
            _ = s.encryption_key_bytes


class TestEnvTemplateContainsNoSecrets:
    """`.env.example` must list every required variable with an empty
    value or placeholder — never a real key/password."""

    @staticmethod
    def _read_template() -> str:
        here = Path(__file__).resolve().parents[2]
        return (here / ".env.example").read_text()

    def test_template_exists_and_lists_required_vars(self) -> None:
        text = self._read_template()
        for var in (
            "LITELLM_MASTER_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "POSTGRES_PASSWORD",
            "REDIS_PASSWORD",
            "ENCRYPTION_KEY",
            "COLLECTOR_DATABASE_URL",
        ):
            assert var in text, f"missing required key in .env.example: {var}"

    def test_template_carries_no_real_openai_key(self) -> None:
        text = self._read_template()
        # Real OpenAI keys start with `sk-` followed by 20+ chars.
        # The template must never embed one.
        for line in text.splitlines():
            assert "sk-proj-" not in line
            assert "sk-ant-" not in line
            # Allow placeholder/comment lines but not literal openai sk-...
            if "OPENAI_API_KEY=" in line:
                value = line.split("=", 1)[1].strip()
                # Either empty or a placeholder in angle brackets.
                assert value == "" or value.startswith("<"), (
                    f"OPENAI_API_KEY must be blank in .env.example, got: {value!r}"
                )

    def test_template_carries_no_real_db_password(self) -> None:
        text = self._read_template()
        for line in text.splitlines():
            if "POSTGRES_PASSWORD=" in line:
                value = line.split("=", 1)[1].split("#", 1)[0].strip()
                assert value == "" or value.startswith("<"), (
                    f"POSTGRES_PASSWORD must be blank in .env.example, got: {value!r}"
                )
