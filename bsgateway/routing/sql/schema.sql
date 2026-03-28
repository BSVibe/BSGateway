CREATE TABLE IF NOT EXISTS routing_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- 원본 텍스트 (분류 검증 + 재학습용)
    user_text TEXT NOT NULL,
    system_prompt TEXT DEFAULT '',
    -- 수치 features (ML 학습용)
    token_count INTEGER,
    conversation_turns INTEGER,
    code_block_count INTEGER,
    code_lines INTEGER,
    has_error_trace BOOLEAN,
    tool_count INTEGER,
    -- 분류 결과 (labels)
    tier TEXT NOT NULL,
    strategy TEXT NOT NULL,
    score INTEGER,
    -- 라우팅 결과
    original_model TEXT NOT NULL,
    resolved_model TEXT NOT NULL,
    -- 임베딩 (BYTEA, float32 array)
    embedding BYTEA,
    -- BSNexus 메타데이터
    nexus_task_type TEXT,
    nexus_priority TEXT,
    nexus_complexity_hint INTEGER,
    decision_source TEXT
);

CREATE INDEX IF NOT EXISTS idx_routing_logs_tier ON routing_logs(tier);
CREATE INDEX IF NOT EXISTS idx_routing_logs_timestamp ON routing_logs(timestamp);
