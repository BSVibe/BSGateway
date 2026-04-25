CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    scopes JSONB NOT NULL DEFAULT '["chat"]',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Legacy unsalted SHA-256 hashes had a UNIQUE(key_hash) constraint.
-- Salted PBKDF2 hashes are unique by construction (random salt) so the
-- constraint is no longer meaningful; drop it if it exists.
ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_key_hash_key;

CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(key_prefix);

-- Audit M4: list_api_keys_by_tenant filters tenant_id and orders by
-- created_at DESC. The composite lets PG walk the index in order
-- without a separate sort step.
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant_created
    ON api_keys(tenant_id, created_at DESC);

-- Drop the obsolete hash-lookup index; we now look up by key_prefix.
DROP INDEX IF EXISTS idx_api_keys_hash;

-- Lockin decision #2 (2026-04-25): purge any legacy unsalted SHA-256
-- digests left over from the pre-Sprint-1 implementation. PBKDF2 hashes
-- always start with the algorithm tag, so any row whose key_hash does
-- NOT begin with "pbkdf2_" predates the rotation and is invalidated.
DELETE FROM api_keys WHERE key_hash NOT LIKE 'pbkdf2_%';
