-- name: insert_feedback
INSERT INTO routing_feedback (tenant_id, routing_id, rating, comment)
VALUES ($1, $2, $3, $4)
RETURNING id, tenant_id, routing_id, rating, comment, created_at;

-- name: list_feedback
SELECT id, tenant_id, routing_id, rating, comment, created_at
FROM routing_feedback WHERE tenant_id = $1
ORDER BY created_at DESC LIMIT $2 OFFSET $3;

-- name: get_feedback_stats
SELECT
    COUNT(*) as total,
    AVG(rating) as avg_rating,
    COUNT(*) FILTER (WHERE rating >= 4) as positive,
    COUNT(*) FILTER (WHERE rating <= 2) as negative
FROM routing_feedback WHERE tenant_id = $1;
