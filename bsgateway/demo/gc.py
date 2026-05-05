"""Re-export demo tenant GC from the shared bsvibe-demo package.

CLI wrapper stays in BSGateway because it imports product-specific config
(``bsgateway.core.config.settings.collector_database_url``).
"""

from __future__ import annotations

from bsvibe_demo import demo_gc, find_expired_tenants

__all__ = ["demo_gc", "find_expired_tenants"]


def main() -> None:
    """CLI entrypoint: ``python -m bsgateway.demo.gc``."""
    import asyncio
    import os

    from bsvibe_demo.gc import run_gc_cli

    from bsgateway.core.config import settings

    if not settings.collector_database_url:
        raise RuntimeError("COLLECTOR_DATABASE_URL is required for demo GC")
    ttl = int(os.environ.get("DEMO_TTL_SECONDS", "7200"))
    count = asyncio.run(run_gc_cli(settings.collector_database_url, ttl_seconds=ttl))
    print(f"demo_gc: deleted {count} expired tenant(s)")


if __name__ == "__main__":
    main()
