"""Re-export demo JWT helpers from the shared bsvibe-demo package.

Kept as a stable BSGateway-side import path so existing call sites
(``from bsgateway.demo.jwt import ...``) keep working as bsvibe-demo
evolves.
"""

from __future__ import annotations

from bsvibe_demo import (
    DemoClaims,
    DemoJWTError,
    decode_demo_jwt,
    mint_demo_jwt,
)

__all__ = [
    "DemoClaims",
    "DemoJWTError",
    "decode_demo_jwt",
    "mint_demo_jwt",
]
