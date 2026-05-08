"""TASK-002 — token-cutover Settings fields.

bsgateway/core/config.py exposes the bootstrap admin token + RFC 7662
introspection knobs that the new bsvibe-authz 3-way dispatch consumes.
Field names mirror :class:`bsvibe_authz.Settings` so a single ``.env``
feeds both Settings classes.
"""

from __future__ import annotations

import hashlib

import pytest

from bsgateway.core.config import Settings

_REQUIRED_ENV: dict[str, str] = {"ENCRYPTION_KEY": "aa" * 32}


@pytest.fixture(autouse=True)
def _stable_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "BOOTSTRAP_TOKEN",
        "BOOTSTRAP_TOKEN_HASH",
        "INTROSPECTION_URL",
        "INTROSPECTION_CLIENT_ID",
        "INTROSPECTION_CLIENT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


class TestTokenCutoverDefaults:
    def test_defaults_are_empty(self) -> None:
        s = Settings()
        assert s.bootstrap_token == ""
        assert s.introspection_url == ""
        assert s.introspection_client_id == ""
        assert s.introspection_client_secret == ""

    def test_default_hash_is_empty(self) -> None:
        s = Settings()
        assert s.bootstrap_token_hash == ""


class TestTokenCutoverEnvLoading:
    def test_fields_loaded_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BOOTSTRAP_TOKEN", "bsv_admin_secret123")
        monkeypatch.setenv("INTROSPECTION_URL", "https://auth.bsvibe.dev/oauth/introspect")
        monkeypatch.setenv("INTROSPECTION_CLIENT_ID", "bsgateway")
        monkeypatch.setenv("INTROSPECTION_CLIENT_SECRET", "shh")

        s = Settings()

        assert s.bootstrap_token == "bsv_admin_secret123"
        assert s.introspection_url == "https://auth.bsvibe.dev/oauth/introspect"
        assert s.introspection_client_id == "bsgateway"
        assert s.introspection_client_secret == "shh"


class TestBootstrapHashDerivation:
    """Raw ``BOOTSTRAP_TOKEN`` is hashed in-memory; pre-hashed
    ``BOOTSTRAP_TOKEN_HASH`` overrides the derived value so prod can
    avoid putting the raw token in process memory at all.
    """

    def test_hash_derived_from_raw_token(self) -> None:
        raw = "bsv_admin_secret123"
        s = Settings(bootstrap_token=raw)

        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert s.bootstrap_token_hash == expected

    def test_pre_hashed_value_takes_precedence(self) -> None:
        pre_hashed = "deadbeef" * 8
        s = Settings(bootstrap_token="bsv_admin_secret123", bootstrap_token_hash=pre_hashed)
        assert s.bootstrap_token_hash == pre_hashed

    def test_pre_hashed_only(self) -> None:
        pre_hashed = "cafebabe" * 8
        s = Settings(bootstrap_token_hash=pre_hashed)
        assert s.bootstrap_token == ""
        assert s.bootstrap_token_hash == pre_hashed
