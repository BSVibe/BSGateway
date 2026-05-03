-- name: insert_tenant
INSERT INTO tenants (name, slug, settings)
VALUES ($1, $2, $3)
RETURNING id, name, slug, is_active, settings, created_at, updated_at;

-- name: insert_tenant_with_id
INSERT INTO tenants (id, name, slug, settings)
VALUES ($1, $2, $3, $4)
ON CONFLICT (id) DO NOTHING
RETURNING id, name, slug, is_active, settings, created_at, updated_at;

-- name: get_tenant_by_id
SELECT id, name, slug, is_active, settings, created_at, updated_at
FROM tenants WHERE id = $1;

-- name: get_tenant_by_slug
SELECT id, name, slug, is_active, settings, created_at, updated_at
FROM tenants WHERE slug = $1;

-- name: list_tenants
SELECT id, name, slug, is_active, settings, created_at, updated_at
FROM tenants WHERE is_active = TRUE ORDER BY created_at DESC LIMIT $1 OFFSET $2;

-- name: update_tenant
UPDATE tenants SET name = $2, slug = $3, settings = $4, updated_at = NOW()
WHERE id = $1
RETURNING id, name, slug, is_active, settings, created_at, updated_at;

-- name: deactivate_tenant
UPDATE tenants SET is_active = FALSE, updated_at = NOW()
WHERE id = $1;

-- name: insert_tenant_model
INSERT INTO tenant_models (tenant_id, model_name, provider, litellm_model, api_key_encrypted, api_base, extra_params)
VALUES ($1, $2, $3, $4, $5, $6, $7)
RETURNING id, tenant_id, model_name, provider, litellm_model, api_base, is_active, extra_params, created_at, updated_at;

-- name: upsert_worker_model
INSERT INTO tenant_models (tenant_id, model_name, provider, litellm_model, api_key_encrypted, api_base, extra_params, is_active)
VALUES ($1, $2, 'executor', $3, NULL, NULL, $4, TRUE)
ON CONFLICT (tenant_id, model_name) DO UPDATE
SET provider = EXCLUDED.provider,
    litellm_model = EXCLUDED.litellm_model,
    extra_params = EXCLUDED.extra_params,
    is_active = TRUE,
    updated_at = NOW()
RETURNING id, model_name;

-- name: delete_worker_model
DELETE FROM tenant_models
WHERE tenant_id = $1 AND model_name = $2 AND provider = 'executor'
  AND (extra_params->>'worker_id') = $3;

-- name: delete_worker_models_by_worker_id
DELETE FROM tenant_models
WHERE tenant_id = $1 AND provider = 'executor'
  AND (extra_params->>'worker_id') = $2;

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

-- name: list_active_models_with_keys
SELECT id, tenant_id, model_name, provider, litellm_model,
       api_key_encrypted, api_base, is_active, extra_params
FROM tenant_models WHERE tenant_id = $1 AND is_active = TRUE
ORDER BY model_name;
