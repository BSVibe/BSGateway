"""Demo auth dependency — replaces ``get_auth_context`` when in demo mode.

Reads the JWT from ``Authorization: Bearer ...`` OR the
``bsvibe_demo_session`` cookie (cross-domain SPAs use cookies). Verifies
with ``DEMO_JWT_SECRET`` (NOT prod auth.bsvibe.dev) and returns a
``GatewayAuthContext`` with ``tenant_id`` so existing tenant-scoped
queries work unchanged.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request, status

from bsgateway.api.deps import AuthIdentity, GatewayAuthContext
from bsgateway.demo.jwt import DemoJWTError, decode_demo_jwt

DEMO_COOKIE_NAME = "bsvibe_demo_session"


def get_demo_jwt_secret() -> str:
    """FastAPI dep: read DEMO_JWT_SECRET from env (override in tests)."""
    secret = os.environ.get("DEMO_JWT_SECRET", "")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="DEMO_JWT_SECRET not configured on demo backend",
        )
    return secret


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get(DEMO_COOKIE_NAME)


async def demo_auth_context(request: Request, *, secret: str | None = None) -> GatewayAuthContext:
    """Demo equivalent of ``get_auth_context``.

    Returns a ``GatewayAuthContext`` whose ``tenant_id`` is read from the
    demo JWT. Existing tenant-scoped queries continue to work.
    """
    secret = secret or get_demo_jwt_secret()
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Demo session not started — POST /api/v1/demo/session first",
        )

    try:
        claims = decode_demo_jwt(token, secret=secret)
    except DemoJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid demo session: {e}",
        ) from e

    return GatewayAuthContext(
        identity=AuthIdentity(
            kind="user",
            id=str(claims.tenant_id),  # synthetic user id == tenant for demo
            email="demo@bsvibe.dev",
        ),
        tenant_id=claims.tenant_id,
        is_admin=False,
    )
