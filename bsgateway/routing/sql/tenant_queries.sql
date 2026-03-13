-- name: insert_tenant
INSERT INTO tenants (name, slug, settings)
VALUES ($1, $2, $3)
RETURNING id, name, slug, is_active, settings, created_at, updated_at;

-- name: get_tenant_by_id
SELECT id, name, slug, is_active, settings, created_at, updated_at
FROM tenants WHERE id = $1;

-- name: get_tenant_by_slug
SELECT id, name, slug, is_active, settings, created_at, updated_at
FROM tenants WHERE slug = $1;

-- name: list_tenants
SELECT id, name, slug, is_active, settings, created_at, updated_at
FROM tenants ORDER BY created_at DESC LIMIT $1 OFFSET $2;

-- name: update_tenant
UPDATE tenants SET name = $2, slug = $3, settings = $4, updated_at = NOW()
WHERE id = $1
RETURNING id, name, slug, is_active, settings, created_at, updated_at;

-- name: deactivate_tenant
UPDATE tenants SET is_active = FALSE, updated_at = NOW()
WHERE id = $1;

-- name: insert_api_key
INSERT INTO tenant_api_keys (tenant_id, key_hash, key_prefix, name, scopes)
VALUES ($1, $2, $3, $4, $5)
RETURNING id, tenant_id, key_prefix, name, scopes, is_active, expires_at, created_at;

-- name: get_api_key_by_hash
SELECT ak.id, ak.tenant_id, ak.key_hash, ak.key_prefix, ak.name,
       ak.scopes, ak.is_active, ak.expires_at, ak.last_used_at, ak.created_at,
       t.is_active as tenant_is_active
FROM tenant_api_keys ak
JOIN tenants t ON t.id = ak.tenant_id
WHERE ak.key_hash = $1;

-- name: list_api_keys
SELECT id, tenant_id, key_prefix, name, scopes, is_active, expires_at, last_used_at, created_at
FROM tenant_api_keys WHERE tenant_id = $1 ORDER BY created_at DESC;

-- name: revoke_api_key
UPDATE tenant_api_keys SET is_active = FALSE WHERE id = $1 AND tenant_id = $2;

-- name: touch_api_key
UPDATE tenant_api_keys SET last_used_at = NOW() WHERE key_hash = $1;

-- name: insert_tenant_model
INSERT INTO tenant_models (tenant_id, model_name, provider, litellm_model, api_key_encrypted, api_base, extra_params)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING id, tenant_id, model_name, provider, litellm_model, api_base, is_active, extra_params, created_at, updated_at;

-- name: get_tenant_model
SELECT id, tenant_id, model_name, provider, litellm_model, api_key_encrypted, api_base,
       is_active, extra_params, created_at, updated_at
FROM tenant_models WHERE id = $1 AND tenant_id = $2;

-- name: get_tenant_model_by_name
SELECT id, tenant_id, model_name, provider, litellm_model, api_key_encrypted, api_base,
       is_active, extra_params, created_at, updated_at
FROM tenant_models WHERE tenant_id = $1 AND model_name = $2;

-- name: list_tenant_models
SELECT id, tenant_id, model_name, provider, litellm_model, api_base,
       is_active, extra_params, created_at, updated_at
FROM tenant_models WHERE tenant_id = $1 ORDER BY model_name;

-- name: update_tenant_model
UPDATE tenant_models
SET model_name = $3, provider = $4, litellm_model = $5,
    api_key_encrypted = $6, api_base = $7, extra_params = $8, updated_at = NOW()
WHERE id = $1 AND tenant_id = $2
RETURNING id, tenant_id, model_name, provider, litellm_model, api_base, is_active, extra_params, created_at, updated_at;

-- name: delete_tenant_model
DELETE FROM tenant_models WHERE id = $1 AND tenant_id = $2;
