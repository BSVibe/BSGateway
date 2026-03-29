"""Seed Supabase users and local DB tenants for development.

Usage:
    COLLECTOR_DATABASE_URL=postgresql://... python scripts/seed_supabase.py

Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY env vars
(or pass via CLI args).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from uuid import uuid4

import asyncpg
import httpx
import structlog

from bsgateway.core.config import settings

logger = structlog.get_logger(__name__)

SUPABASE_URL = settings.supabase_url

# Seed data: (email, password, role, tenant_name, tenant_slug)
SEED_USERS = [
    {
        "email": "admin@bsvibe.dev",
        "password": "admin1234!",
        "role": "admin",
        "tenant_name": "BSVibe Dev",
        "tenant_slug": "bsvibe-dev",
    },
    {
        "email": "user@bsvibe.dev",
        "password": "user1234!",
        "role": "member",
        "tenant_name": "BSVibe Dev",
        "tenant_slug": "bsvibe-dev",
    },
]


async def ensure_tenant(pool: asyncpg.Pool, name: str, slug: str) -> str:
    """Create tenant if not exists, return tenant_id as string."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM tenants WHERE slug = $1", slug)
        if row:
            tid = str(row["id"])
            logger.info("tenant_exists", slug=slug, tenant_id=tid)
            return tid

        tid = str(uuid4())
        await conn.execute(
            """
            INSERT INTO tenants (id, name, slug, is_active, settings)
            VALUES ($1::uuid, $2, $3, true, $4)
            """,
            tid,
            name,
            slug,
            json.dumps({}),
        )
        logger.info("tenant_created", slug=slug, tenant_id=tid)
        return tid


async def create_supabase_user(
    client: httpx.AsyncClient,
    service_role_key: str,
    email: str,
    password: str,
    tenant_id: str,
    role: str,
) -> dict | None:
    """Create a user via Supabase Admin API."""
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }

    # Check if user already exists
    resp = await client.get(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=headers,
        params={"per_page": 100},
    )
    resp.raise_for_status()
    existing = [u for u in resp.json().get("users", []) if u["email"] == email]
    if existing:
        user = existing[0]
        logger.info("user_exists", email=email, user_id=user["id"])
        # Update app_metadata if needed
        await client.put(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user['id']}",
            headers=headers,
            json={
                "app_metadata": {"tenant_id": tenant_id, "role": role},
            },
        )
        logger.info("user_metadata_updated", email=email, tenant_id=tenant_id, role=role)
        return user

    # Create new user
    resp = await client.post(
        f"{SUPABASE_URL}/auth/v1/admin/users",
        headers=headers,
        json={
            "email": email,
            "password": password,
            "email_confirm": True,
            "app_metadata": {"tenant_id": tenant_id, "role": role},
        },
    )
    resp.raise_for_status()
    user = resp.json()
    logger.info("user_created", email=email, user_id=user["id"], role=role)
    return user


async def get_access_token(
    client: httpx.AsyncClient,
    service_role_key: str,
    email: str,
    password: str,
) -> str:
    """Sign in and return access_token for testing."""
    resp = await client.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={
            "apikey": service_role_key,
            "Content-Type": "application/json",
        },
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def main() -> None:
    service_role_key = (
        sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    )  # noqa: E501
    if not service_role_key:
        print("ERROR: SUPABASE_SERVICE_ROLE_KEY env var or CLI arg required")
        sys.exit(1)

    if not SUPABASE_URL:
        print("ERROR: SUPABASE_URL not set")
        sys.exit(1)

    db_url = settings.collector_database_url
    if not db_url:
        print("ERROR: COLLECTOR_DATABASE_URL not set")
        sys.exit(1)

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

    # Collect unique tenants
    tenant_map: dict[str, str] = {}  # slug -> tenant_id

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            print("\n=== Seeding tenants & users ===\n")

            for seed in SEED_USERS:
                slug = seed["tenant_slug"]
                if slug not in tenant_map:
                    tenant_map[slug] = await ensure_tenant(pool, seed["tenant_name"], slug)

                tenant_id = tenant_map[slug]
                await create_supabase_user(
                    client,
                    service_role_key,
                    seed["email"],
                    seed["password"],
                    tenant_id,
                    seed["role"],
                )

            # Generate tokens for testing
            print("\n=== Access Tokens (for testing) ===\n")
            for seed in SEED_USERS:
                token = await get_access_token(
                    client,
                    service_role_key,
                    seed["email"],
                    seed["password"],
                )
                print(f"  {seed['email']} ({seed['role']}):")
                print(f"    {token}\n")

            print("=== Test command ===\n")
            admin_token = await get_access_token(
                client, service_role_key, "admin@bsvibe.dev", "admin1234!"
            )
            print("  curl -s http://localhost:8000/api/v1/tenants \\")
            print(f'    -H "Authorization: Bearer {admin_token}" | python3 -m json.tool')
            print()

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
