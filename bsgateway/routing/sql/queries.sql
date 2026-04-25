-- name: insert_routing_log
-- All routing_logs writes MUST scope by tenant_id. The previous
-- no-tenant variant has been removed deliberately — see
-- `Docs/BSVibe_Ecosystem_Audit.md` §5.1 (C2). Use
-- `RoutingLogsRepository.insert_routing_log` instead of executing
-- this query directly.
INSERT INTO routing_logs
    (tenant_id, rule_id,
     user_text, system_prompt,
     token_count, conversation_turns, code_block_count,
     code_lines, has_error_trace, tool_count,
     tier, strategy, score,
     original_model, resolved_model, embedding,
     nexus_task_type, nexus_priority, nexus_complexity_hint, decision_source)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20);

-- name: get_logs_by_tier
SELECT * FROM routing_logs
WHERE tenant_id = $1 AND tier = $2
ORDER BY timestamp DESC LIMIT $3;

-- name: get_logs_with_embeddings
SELECT id, user_text, tier, embedding FROM routing_logs
WHERE tenant_id = $1 AND embedding IS NOT NULL
ORDER BY timestamp DESC;

-- name: count_by_tier
SELECT tier, COUNT(*) as count FROM routing_logs
WHERE tenant_id = $1
GROUP BY tier;

-- name: usage_by_model
SELECT DATE(timestamp) as day, resolved_model,
       COUNT(*) as requests, COALESCE(SUM(token_count), 0) as tokens
FROM routing_logs
WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp < $3
GROUP BY DATE(timestamp), resolved_model
ORDER BY day;

-- name: usage_by_rule
SELECT rl.rule_id, rr.name as rule_name, COUNT(*) as requests
FROM routing_logs rl
LEFT JOIN routing_rules rr ON rl.rule_id = rr.id
WHERE rl.tenant_id = $1 AND rl.timestamp >= $2 AND rl.timestamp < $3
  AND rl.rule_id IS NOT NULL
GROUP BY rl.rule_id, rr.name;

-- name: usage_total
SELECT COUNT(*) as total_requests,
       COALESCE(SUM(token_count), 0) as total_tokens
FROM routing_logs
WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp < $3;
