-- name: insert_audit_log
INSERT INTO audit_logs (tenant_id, actor, action, resource_type, resource_id, details)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id, tenant_id, actor, action, resource_type, resource_id, details, created_at;

-- name: list_audit_logs
SELECT id, tenant_id, actor, action, resource_type, resource_id, details, created_at
FROM audit_logs
WHERE tenant_id = $1
ORDER BY created_at DESC
LIMIT $2 OFFSET $3;

-- name: count_audit_logs
SELECT COUNT(*) as total FROM audit_logs WHERE tenant_id = $1;
