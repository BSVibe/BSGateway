-- Feedback table for quality tracking

CREATE TABLE IF NOT EXISTS routing_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    -- NOTE: routing_id is TEXT (not FK) because routing_logs may be purged
    -- independently. Orphaned feedback rows are acceptable and can be cleaned
    -- up via periodic maintenance queries.
    routing_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_tenant ON routing_feedback(tenant_id);
CREATE INDEX IF NOT EXISTS idx_feedback_routing ON routing_feedback(routing_id);
