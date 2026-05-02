-- name: insert_rule
INSERT INTO routing_rules (tenant_id, name, priority, is_default, target_model)
VALUES ($1, $2, $3, $4, $5)
RETURNING id, tenant_id, name, priority, is_active, is_default, target_model,
          created_at, updated_at;

-- name: get_rule
SELECT id, tenant_id, name, priority, is_active, is_default, target_model,
       created_at, updated_at
FROM routing_rules WHERE id = $1 AND tenant_id = $2;

-- name: list_rules
SELECT id, tenant_id, name, priority, is_active, is_default, target_model,
       created_at, updated_at
FROM routing_rules WHERE tenant_id = $1 ORDER BY priority ASC;

-- name: update_rule
UPDATE routing_rules
SET name = $3, priority = $4, is_default = $5, target_model = $6, updated_at = NOW()
WHERE id = $1 AND tenant_id = $2
RETURNING id, tenant_id, name, priority, is_active, is_default, target_model,
          created_at, updated_at;

-- name: delete_rule
DELETE FROM routing_rules WHERE id = $1 AND tenant_id = $2;

-- name: insert_condition
INSERT INTO rule_conditions (rule_id, condition_type, operator, field, value, negate)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id, rule_id, condition_type, operator, field, value, negate;

-- name: insert_condition_batch
-- Same as insert_condition but without RETURNING — used by executemany()
-- in RulesRepository.replace_conditions to fold N inserts into a single
-- batched round-trip (audit M3). asyncpg's executemany rejects RETURNING.
INSERT INTO rule_conditions (rule_id, condition_type, operator, field, value, negate)
VALUES ($1, $2, $3, $4, $5, $6);

-- name: list_conditions
SELECT id, rule_id, condition_type, operator, field, value, negate
FROM rule_conditions WHERE rule_id = $1;

-- name: delete_conditions_for_rule
DELETE FROM rule_conditions WHERE rule_id = $1;

-- name: list_conditions_for_tenant
SELECT c.id, c.rule_id, c.condition_type, c.operator, c.field, c.value, c.negate
FROM rule_conditions c
JOIN routing_rules r ON r.id = c.rule_id
WHERE r.tenant_id = $1;

-- name: update_rule_priority
UPDATE routing_rules SET priority = $3, updated_at = NOW()
WHERE id = $1 AND tenant_id = $2;

-- name: insert_intent
INSERT INTO tenant_intents (tenant_id, name, description, threshold)
VALUES ($1, $2, $3, $4)
RETURNING id, tenant_id, name, description, threshold, is_active, created_at, updated_at;

-- name: get_intent
SELECT id, tenant_id, name, description, threshold, is_active, created_at, updated_at
FROM tenant_intents WHERE id = $1 AND tenant_id = $2;

-- name: get_intent_by_name
SELECT id, tenant_id, name, description, threshold, is_active, created_at, updated_at
FROM tenant_intents WHERE tenant_id = $1 AND name = $2;

-- name: list_intents
SELECT id, tenant_id, name, description, threshold, is_active, created_at, updated_at
FROM tenant_intents WHERE tenant_id = $1 ORDER BY name;

-- name: update_intent
UPDATE tenant_intents
SET name = $3, description = $4, threshold = $5, updated_at = NOW()
WHERE id = $1 AND tenant_id = $2
RETURNING id, tenant_id, name, description, threshold, is_active, created_at, updated_at;

-- name: delete_intent
DELETE FROM tenant_intents WHERE id = $1 AND tenant_id = $2;

-- name: insert_intent_example
INSERT INTO intent_examples (intent_id, text, embedding, embedding_model)
VALUES ($1, $2, $3, $4)
RETURNING id, intent_id, text, created_at;

-- name: list_intent_examples
SELECT id, intent_id, text, embedding, embedding_model, created_at
FROM intent_examples WHERE intent_id = $1 ORDER BY created_at;

-- name: delete_intent_example
DELETE FROM intent_examples WHERE id = $1 AND intent_id = $2;

-- name: list_intent_examples_for_tenant
SELECT e.id, e.intent_id, e.text, e.embedding, e.embedding_model, e.created_at,
       i.name as intent_name, i.threshold
FROM intent_examples e
JOIN tenant_intents i ON i.id = e.intent_id
WHERE i.tenant_id = $1 AND i.is_active = TRUE;

-- name: list_examples_needing_reembedding
SELECT e.id, e.text, e.embedding_model
FROM intent_examples e
JOIN tenant_intents i ON i.id = e.intent_id
WHERE i.tenant_id = $1
  AND (e.embedding IS NULL OR e.embedding_model IS DISTINCT FROM $2);

-- name: update_intent_example_embedding
UPDATE intent_examples
SET embedding = $2, embedding_model = $3
WHERE id = $1;
