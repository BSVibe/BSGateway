-- name: insert_api_key
INSERT INTO api_keys (tenant_id, name, key_hash, key_prefix, scopes, expires_at)
VALUES ($1, $2, $3, $4, $5::jsonb, $6)
RETURNING id, tenant_id, name, key_hash, key_prefix, scopes, is_active, expires_at, last_used_at, created_at;

-- name: list_api_keys_by_prefix
SELECT id, tenant_id, name, key_hash, key_prefix, scopes, is_active, expires_at, last_used_at, created_at
FROM api_keys WHERE key_prefix = $1;

-- name: list_api_keys_by_tenant
SELECT id, tenant_id, name, key_prefix, scopes, is_active, expires_at, last_used_at, created_at
FROM api_keys WHERE tenant_id = $1 ORDER BY created_at DESC;

-- name: revoke_api_key
UPDATE api_keys SET is_active = FALSE WHERE id = $1 AND tenant_id = $2;

-- name: touch_last_used
UPDATE api_keys SET last_used_at = NOW() WHERE id = $1;
