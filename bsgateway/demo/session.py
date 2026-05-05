"""Re-export demo session helpers from the shared bsvibe-demo package.

The session service is product-agnostic: it inserts a row into the
``tenants`` table (identical schema across products) and calls a caller-
supplied ``seed_fn``. BSGateway-side seeding lives in
:mod:`bsgateway.demo.seed`.
"""

from __future__ import annotations

from bsvibe_demo import DemoSessionResult, DemoSessionService, SeedFn

__all__ = ["DemoSessionResult", "DemoSessionService", "SeedFn"]
