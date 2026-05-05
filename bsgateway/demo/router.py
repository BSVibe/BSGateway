"""Demo HTTP endpoints — visitor entry point.

Mounted at ``/api/v1/demo/*`` on the demo backend only (gated by
``BSVIBE_DEMO_MODE=true`` in app.py wiring). The prod backend never sees
these routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from bsgateway.api.deps import get_pool
from bsgateway.demo.auth import DEMO_COOKIE_NAME, demo_auth_context, get_demo_jwt_secret
from bsgateway.demo.seed import seed_demo
from bsgateway.demo.session import DemoSessionResult, DemoSessionService

demo_router = APIRouter(prefix="/demo", tags=["demo"])


class DemoSessionResponse(BaseModel):
    tenant_id: str
    token: str
    expires_in: int


def get_demo_session_service(
    request: Request,
    secret: str = Depends(get_demo_jwt_secret),
) -> DemoSessionService:
    """FastAPI dep: build a DemoSessionService bound to the app pool."""
    pool = get_pool(request)
    return DemoSessionService(
        pool=pool,
        jwt_secret=secret,
        seed_fn=seed_demo,
        session_ttl_seconds=7200,
    )


@demo_router.post(
    "/session",
    status_code=status.HTTP_201_CREATED,
    response_model=DemoSessionResponse,
    summary="Create a fresh demo session (ephemeral tenant + JWT)",
)
async def post_demo_session(
    response: Response,
    service: DemoSessionService = Depends(get_demo_session_service),
) -> DemoSessionResponse:
    """Create a new ephemeral demo tenant + seed it + return a JWT.

    Sets ``bsvibe_demo_session`` cookie so subsequent requests authenticate
    automatically. Frontend can also pull ``token`` from the JSON body
    for cross-domain Authorization headers.
    """
    result: DemoSessionResult = await service.create_session()

    response.set_cookie(
        key=DEMO_COOKIE_NAME,
        value=result.token,
        max_age=result.expires_in,
        httponly=True,
        secure=True,
        samesite="lax",
    )

    return DemoSessionResponse(
        tenant_id=str(result.tenant_id),
        token=result.token,
        expires_in=result.expires_in,
    )


@demo_router.post(
    "/refresh",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Touch last_active so GC won't reap the tenant",
)
async def post_demo_refresh(
    request: Request,
    service: DemoSessionService = Depends(get_demo_session_service),
) -> Response:
    """Touch ``last_active_at`` for the current demo session."""
    auth = await demo_auth_context(request)
    await service.touch_last_active(auth.tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
