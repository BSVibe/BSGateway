"""Demo session module — public interactive demo backend.

Per-visitor ephemeral tenants, separate JWT issuer (DEMO_JWT_SECRET, NOT
prod auth.bsvibe.dev), tenant GC every hour for tenants inactive >2h.

Components:
- ``jwt``: mint/decode demo session JWTs
- ``session``: tenant creation + seed orchestration
- ``seed``: per-tenant demo data insertion
- ``guard``: blocks real LLM calls when BSVIBE_DEMO_MODE=true
- ``gc``: cascade-deletes expired tenants
"""
