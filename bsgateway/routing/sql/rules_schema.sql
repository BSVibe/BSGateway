-- Rule engine tables

CREATE TABLE IF NOT EXISTS routing_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    target_model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, name),
    UNIQUE(tenant_id, priority) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_rules_tenant_priority
    ON routing_rules(tenant_id, priority);

CREATE TABLE IF NOT EXISTS rule_conditions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id UUID NOT NULL REFERENCES routing_rules(id) ON DELETE CASCADE,
    condition_type TEXT NOT NULL,
    operator TEXT NOT NULL DEFAULT 'eq',
    field TEXT NOT NULL,
    value JSONB NOT NULL,
    negate BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_conditions_rule ON rule_conditions(rule_id);

-- Custom intent tables

CREATE TABLE IF NOT EXISTS tenant_intents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    threshold REAL NOT NULL DEFAULT 0.7,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(tenant_id, name)
);

CREATE INDEX IF NOT EXISTS idx_intents_tenant ON tenant_intents(tenant_id);

CREATE TABLE IF NOT EXISTS intent_examples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_id UUID NOT NULL REFERENCES tenant_intents(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    embedding BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_examples_intent ON intent_examples(intent_id);
