"""bsgateway/core/config.py — RFC 7662 introspection knobs.

Field names mirror :class:`bsvibe_authz.Settings` so a single ``.env``
feeds both Settings classes.
"""

from __future__ import annotations

import pytest

from bsgateway.core.config import Settings

_REQUIRED_ENV: dict[str, str] = {"ENCRYPTION_KEY": "aa" * 32}


@pytest.fixture(autouse=True)
def _stable_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "INTROSPECTION_URL",
        "INTROSPECTION_CLIENT_ID",
        "INTROSPECTION_CLIENT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


class TestIntrospectionDefaults:
    def test_defaults_are_empty(self) -> None:
        s = Settings()
        assert s.introspection_url == ""
        assert s.introspection_client_id == ""
        assert s.introspection_client_secret == ""


class TestIntrospectionEnvLoading:
    def test_fields_loaded_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INTROSPECTION_URL", "https://auth.bsvibe.dev/oauth/introspect")
        monkeypatch.setenv("INTROSPECTION_CLIENT_ID", "bsgateway")
        monkeypatch.setenv("INTROSPECTION_CLIENT_SECRET", "shh")

        s = Settings()

        assert s.introspection_url == "https://auth.bsvibe.dev/oauth/introspect"
        assert s.introspection_client_id == "bsgateway"
        assert s.introspection_client_secret == "shh"
