-- Tenant management tables

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    settings JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    litellm_model TEXT NOT NULL,
    api_key_encrypted TEXT,
    api_base TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    extra_params JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_tenant_models_tenant ON tenant_models(tenant_id);

-- Extend routing_logs with tenant context
ALTER TABLE routing_logs ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id);
ALTER TABLE routing_logs ADD COLUMN IF NOT EXISTS rule_id UUID;

CREATE INDEX IF NOT EXISTS idx_routing_logs_tenant ON routing_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_routing_logs_tenant_time ON routing_logs(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_routing_logs_rule_id ON routing_logs(rule_id);
