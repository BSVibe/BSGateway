"""Mint short-lived service JWTs for BSGateway → BSupervisor calls.

Service-account pattern (decision recorded in PR description, Lockin §3 #16):

* BSGateway runs with two long-lived secrets in the environment:
  - ``BSVIBE_SERVICE_ACCOUNT_TOKEN`` — a BSVibe-Auth user access token
    minted out-of-band for a service account user (admin/owner of a
    dedicated tenant).
  - ``BSVIBE_SERVICE_ACCOUNT_TENANT_ID`` — the tenant the account is
    operating under.

  At startup we contact BSVibe-Auth's ``POST /api/service-tokens/issue``
  with that bearer token and exchange it for a service-audience JWT
  (e.g. ``aud="bsupervisor"``, ``scope=["bsupervisor.events"]``).

* The minted token is cached in memory and reused until ``exp - safety``.
  A single asyncio lock prevents N concurrent cold-start callers from
  triggering N parallel mints.

* Callers can ``invalidate()`` (e.g. on receiving a 401 from the
  downstream service) to force the next call to mint fresh.

We deliberately do NOT mint on a background timer — instead each
``get_token()`` checks the cache. This keeps the minter passive when
BSupervisor traffic is idle.
"""

from __future__ import annotations

import asyncio
import re
import time

import httpx
import structlog

logger = structlog.get_logger(__name__)

_SUPPORTED_AUDIENCES: frozenset[str] = frozenset(
    ("bsage", "bsgateway", "bsupervisor", "bsnexus"),
)
_SCOPE_PATTERN = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$")


class ServiceTokenMinterError(RuntimeError):
    """Failed to mint a service token (auth-server error / network / config)."""


class ServiceTokenMinter:
    """Mint and cache a service JWT for one (audience, scope) pair.

    A separate instance per ``(audience, scope)`` keeps the cache
    invariants simple — the cached token's claims always match the
    instance's configuration.
    """

    def __init__(
        self,
        *,
        auth_url: str,
        service_account_token: str,
        service_account_tenant_id: str,
        audience: str,
        scope: list[str],
        timeout_s: float = 10.0,
        safety_margin_s: int = 60,
    ) -> None:
        if audience not in _SUPPORTED_AUDIENCES:
            raise ValueError(
                f"audience must be one of {sorted(_SUPPORTED_AUDIENCES)}, got {audience!r}"
            )
        if not scope:
            raise ValueError("scope must not be empty")
        prefix = f"{audience}."
        for s in scope:
            if not _SCOPE_PATTERN.match(s):
                raise ValueError(f"invalid scope identifier: {s!r}")
            if not s.startswith(prefix):
                raise ValueError(f"scope {s!r} does not match audience {audience!r}")

        self._auth_url = auth_url.rstrip("/")
        self._service_account_token = service_account_token
        self._service_account_tenant_id = service_account_tenant_id
        self._audience = audience
        self._scope = list(scope)
        self._timeout_s = timeout_s
        self._safety_margin_s = max(0, int(safety_margin_s))

        self._cached_token: str | None = None
        self._cached_exp: int = 0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return a non-expired service JWT, minting one on first call / after expiry."""
        if self._is_cache_fresh():
            return self._cached_token  # type: ignore[return-value]

        async with self._lock:
            # Re-check under the lock — another waiter may have just minted.
            if self._is_cache_fresh():
                return self._cached_token  # type: ignore[return-value]

            await self._mint()
            return self._cached_token  # type: ignore[return-value]

    def invalidate(self) -> None:
        """Drop the cached token so the next ``get_token`` mints fresh."""
        self._cached_token = None
        self._cached_exp = 0

    def _is_cache_fresh(self) -> bool:
        if self._cached_token is None:
            return False
        return int(time.time()) < (self._cached_exp - self._safety_margin_s)

    async def _mint(self) -> None:
        url = f"{self._auth_url}/api/service-tokens/issue"
        body = {
            "audience": self._audience,
            "scope": self._scope,
            "tenant_id": self._service_account_tenant_id,
        }
        headers = {
            "Authorization": f"Bearer {self._service_account_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as cli:
                resp = await cli.post(url=url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "service_token_mint_http_error",
                status=exc.response.status_code,
                audience=self._audience,
            )
            raise ServiceTokenMinterError(
                f"BSVibe-Auth returned {exc.response.status_code} for service-token mint"
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            logger.error("service_token_mint_failed", error=str(exc))
            raise ServiceTokenMinterError(f"failed to mint service token: {exc}") from exc

        access_token = data.get("access_token")
        expires_in = data.get("expires_in")
        if not isinstance(access_token, str) or not access_token:
            raise ServiceTokenMinterError("malformed service-token response: missing access_token")
        if not isinstance(expires_in, int) or expires_in <= 0:
            raise ServiceTokenMinterError("malformed service-token response: missing expires_in")

        self._cached_token = access_token
        self._cached_exp = int(time.time()) + expires_in
        logger.info(
            "service_token_minted",
            audience=self._audience,
            expires_in=expires_in,
        )
