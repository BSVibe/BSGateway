from __future__ import annotations

import asyncio
import re
import struct
from pathlib import Path
from uuid import UUID

import asyncpg
import litellm
import structlog

from bsgateway.routing.classifiers.base import (
    ClassificationResult,
    extract_all_text,
    extract_system_prompt,
    extract_user_text,
)
from bsgateway.routing.models import EmbeddingConfig, RoutingDecision

logger = structlog.get_logger(__name__)


class SqlLoader:
    """Load and parse .sql files from the sql/ directory."""

    def __init__(self) -> None:
        self._sql_dir = Path(__file__).parent / "sql"
        self._queries: dict[str, str] = {}

    def schema(self) -> str:
        return (self._sql_dir / "schema.sql").read_text()

    def query(self, name: str) -> str:
        if not self._queries:
            self._parse_queries()
        return self._queries[name]

    def _parse_queries(self) -> None:
        for sql_file in sorted(self._sql_dir.glob("*queries.sql")):
            self._parse_file(sql_file)

    def _parse_file(self, path: Path) -> None:
        content = path.read_text()
        current_name: str | None = None
        current_lines: list[str] = []
        for line in content.splitlines():
            if line.strip().startswith("-- name:"):
                if current_name:
                    self._queries[current_name] = "\n".join(current_lines).strip()
                current_name = line.strip().split("-- name:")[1].strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_name:
            self._queries[current_name] = "\n".join(current_lines).strip()


sql = SqlLoader()


class RoutingCollector:
    """Collect routing decisions into PostgreSQL for ML training data.

    Stores original text, numeric features, classification labels,
    and optionally embedding vectors.
    """

    def __init__(
        self,
        database_url: str,
        embedding_config: EmbeddingConfig | None = None,
    ) -> None:
        self.database_url = database_url
        self.embedding_config = embedding_config
        self._pool: asyncpg.Pool = None  # type: ignore[assignment]
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_db(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
            schema = sql.schema()
            async with self._pool.acquire() as conn:
                for statement in schema.split(";"):
                    statement = statement.strip()
                    if statement:
                        await conn.execute(statement)
            self._initialized = True

    async def record(
        self,
        data: dict,
        result: ClassificationResult,
        decision: RoutingDecision,
        *,
        tenant_id: UUID | None,
        rule_id: UUID | None = None,
    ) -> None:
        """Persist a routing decision row.

        ``tenant_id`` is mandatory. Without it the row would be written
        as NULL-tenant and could be co-mingled into another tenant's
        aggregate queries (see C2 in the BSVibe Ecosystem Audit). When
        the caller cannot resolve a tenant — e.g. a bare LiteLLM proxy
        request that did not flow through the BSGateway chat router —
        the record is silently dropped rather than written without
        scoping.
        """
        if tenant_id is None:
            logger.debug(
                "routing_record_skipped_no_tenant",
                reason="record() called without tenant_id; refusing to log "
                "to prevent cross-tenant leakage",
            )
            return

        await self._ensure_db()
        messages = data.get("messages", [])
        user_text = extract_user_text(messages)
        system_prompt = extract_system_prompt(data)
        features = self._extract_features(data, messages)

        embedding_blob = None
        if self.embedding_config:
            embedding_blob = await self._generate_embedding(user_text)

        nexus = decision.nexus_metadata
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql.query("insert_routing_log"),
                tenant_id,
                rule_id,
                user_text,
                system_prompt,
                features["token_count"],
                features["conversation_turns"],
                features["code_block_count"],
                features["code_lines"],
                features["has_error_trace"],
                features["tool_count"],
                result.tier,
                result.strategy,
                result.score,
                decision.original_model,
                decision.resolved_model,
                embedding_blob,
                nexus.task_type if nexus else None,
                nexus.priority if nexus else None,
                nexus.complexity_hint if nexus else None,
                decision.decision_source,
            )

        logger.debug(
            "routing_recorded",
            tier=result.tier,
            strategy=result.strategy,
            has_embedding=embedding_blob is not None,
        )

    async def _generate_embedding(self, text: str) -> bytes | None:
        if not text or not self.embedding_config:
            return None
        try:
            response = await litellm.aembedding(
                model=f"ollama/{self.embedding_config.model}",
                input=[text[: self.embedding_config.max_chars]],
                api_base=self.embedding_config.api_base,
                timeout=self.embedding_config.timeout,
            )
            vector = response.data[0]["embedding"]
            return struct.pack(f"{len(vector)}f", *vector)
        except Exception:
            logger.warning("embedding_generation_failed", exc_info=True)
            return None

    @staticmethod
    def _extract_features(data: dict, messages: list) -> dict:
        all_text = extract_all_text(messages)
        code_blocks = re.findall(r"```[\s\S]*?```", all_text)
        return {
            "token_count": int(len(all_text.split()) * 1.3),
            "conversation_turns": len([m for m in messages if m.get("role") == "user"]),
            "code_block_count": len(code_blocks),
            "code_lines": sum(b.count("\n") for b in code_blocks),
            "has_error_trace": any(p in all_text for p in ["Traceback", "Error:", "Exception"]),
            "tool_count": len(data.get("tools", [])),
        }

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
