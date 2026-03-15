-- name: insert_routing_log
INSERT INTO routing_logs
    (user_text, system_prompt,
     token_count, conversation_turns, code_block_count,
     code_lines, has_error_trace, tool_count,
     tier, strategy, score,
     original_model, resolved_model, embedding)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14);

-- name: get_logs_by_tier
SELECT * FROM routing_logs WHERE tier = $1 ORDER BY timestamp DESC LIMIT $2;

-- name: get_logs_with_embeddings
SELECT id, user_text, tier, embedding FROM routing_logs
WHERE embedding IS NOT NULL ORDER BY timestamp DESC;

-- name: count_by_tier
SELECT tier, COUNT(*) as count FROM routing_logs GROUP BY tier;

-- name: insert_routing_log_with_tenant
INSERT INTO routing_logs
    (tenant_id, rule_id, user_text, system_prompt,
     token_count, conversation_turns, code_block_count,
     code_lines, has_error_trace, tool_count,
     tier, strategy, score,
     original_model, resolved_model)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15);
