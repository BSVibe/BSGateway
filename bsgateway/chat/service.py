from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

try:
    import litellm
except ImportError:  # pragma: no cover
    litellm = None  # type: ignore[assignment]

from bsgateway.core.security import decrypt_value
from bsgateway.core.sql_loader import NamedSqlLoader
from bsgateway.core.utils import parse_jsonb_value, safe_json_loads
from bsgateway.embedding.provider import build_provider
from bsgateway.embedding.serialization import hydrate_intent_definitions
from bsgateway.embedding.settings import EmbeddingSettings
from bsgateway.executor.config import executor_settings
from bsgateway.executor.dispatcher import WorkerDispatcher
from bsgateway.executor.sql_loader import ExecutorSqlLoader
from bsgateway.routing.collector import SqlLoader
from bsgateway.routing.repository import RoutingLogsRepository
from bsgateway.rules.engine import RuleEngine
from bsgateway.rules.intent import IntentClassifier, IntentDefinition
from bsgateway.rules.models import (
    EvaluationContext,
    RoutingRule,
    RuleCondition,
    RuleMatch,
    TenantConfig,
    TenantModel,
)

if TYPE_CHECKING:
    import asyncpg
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

_sql = SqlLoader()
_rules_sql = NamedSqlLoader("rules_schema.sql", "rules_queries.sql")
_executor_sql = ExecutorSqlLoader()


def _last_user_message(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            return content if isinstance(content, str) else str(content)
    return ""


class ChatService:
    """Thin orchestrator: auth → rule evaluation → litellm delegation."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        encryption_key: bytes,
        redis: Redis | None = None,
        background_tasks: set[asyncio.Task] | None = None,
    ) -> None:
        self._pool = pool
        self._encryption_key = encryption_key
        self._redis = redis
        self._engine = RuleEngine()
        self._background_tasks: set[asyncio.Task] = (
            background_tasks if background_tasks is not None else set()
        )

    async def load_tenant_config(self, tenant_id: UUID) -> TenantConfig:
        """Batch-load rules + conditions + models + intent examples for a tenant."""
        async with self._pool.acquire() as conn:
            # 1. Active rules
            rule_rows = await conn.fetch(
                _sql.query("list_rules"),
                tenant_id,
            )
            # 2. Conditions for all of tenant's rules (batch)
            cond_rows = await conn.fetch(
                _sql.query("list_conditions_for_tenant"),
                tenant_id,
            )
            # 3. Active models with encrypted keys
            model_rows = await conn.fetch(
                _sql.query("list_active_models_with_keys"),
                tenant_id,
            )
            # 4. Tenant settings
            tenant_row = await conn.fetchrow(
                _sql.query("get_tenant_by_id"),
                tenant_id,
            )
            # 5. Intent examples (with embedding bytes + embedding_model tag)
            intent_example_rows = await conn.fetch(
                _rules_sql.query("list_intent_examples_for_tenant"),
                tenant_id,
            )

        # Assemble conditions by rule_id
        cond_by_rule: dict[UUID, list] = defaultdict(list)
        for c in cond_rows:
            cond_by_rule[c["rule_id"]].append(c)

        rules: list[RoutingRule] = []
        for r in rule_rows:
            conditions = [
                RuleCondition(
                    condition_type=c["condition_type"],
                    field=c["field"],
                    operator=c["operator"],
                    value=parse_jsonb_value(c["value"]),
                    negate=c["negate"],
                )
                for c in cond_by_rule.get(r["id"], [])
            ]
            rules.append(
                RoutingRule(
                    id=str(r["id"]),
                    tenant_id=str(tenant_id),
                    name=r["name"],
                    priority=r["priority"],
                    is_active=r["is_active"],
                    is_default=r["is_default"],
                    target_model=r["target_model"],
                    conditions=conditions,
                )
            )

        # Build models dict
        models: dict[str, TenantModel] = {}
        for m in model_rows:
            models[m["model_name"]] = TenantModel(
                model_name=m["model_name"],
                provider=m["provider"],
                litellm_model=m["litellm_model"],
                api_key_encrypted=m["api_key_encrypted"],
                api_base=m["api_base"],
                extra_params=safe_json_loads(m["extra_params"]),
            )

        settings = safe_json_loads(tenant_row["settings"]) if tenant_row else {}

        # Hydrate intent definitions, dropping any embeddings that don't match
        # the tenant's currently configured embedding model (stale after a
        # model swap). When the tenant has no embedding model configured at
        # all, hydration returns an empty list and intent classification is
        # skipped entirely.
        embedding_settings = EmbeddingSettings.from_tenant_settings(settings)
        active_model = embedding_settings.model if embedding_settings else None
        intent_definitions = hydrate_intent_definitions(
            intent_example_rows, active_model=active_model
        )

        return TenantConfig(
            tenant_id=str(tenant_id),
            slug=tenant_row["slug"] if tenant_row else "",
            models=models,
            rules=rules,
            settings=settings,
            embedding_settings=embedding_settings,
            intent_definitions=intent_definitions,
        )

    @staticmethod
    def _build_intent_classifier(
        tenant_config: TenantConfig,
    ) -> IntentClassifier | None:
        """Build a per-request IntentClassifier from the tenant's config.

        Returns None when intent classification cannot run for this request:
        either no embedding model is configured, or no intent has any current
        (non-stale) example embeddings.
        """
        if not tenant_config.embedding_settings:
            return None
        intents: list[IntentDefinition] = tenant_config.intent_definitions
        if not intents:
            return None
        provider = build_provider(tenant_config.embedding_settings)
        if provider is None:
            return None

        async def _embed_one(text: str) -> list[float]:
            vectors = await provider.embed([text])
            return vectors[0]

        return IntentClassifier(embed_fn=_embed_one, intents=intents)

    async def resolve_model(
        self,
        tenant_config: TenantConfig,
        request_data: dict,
    ) -> tuple[TenantModel, RuleMatch | None]:
        """Resolve target model: 'auto' → rule engine, specific → direct lookup."""
        requested_model = request_data.get("model", "auto")

        if requested_model != "auto":
            # Direct model lookup
            model = tenant_config.models.get(requested_model)
            if not model:
                raise ModelNotFoundError(
                    f"Model '{requested_model}' is not registered for this tenant"
                )
            return model, None

        # Rule engine evaluation. Build a per-request IntentClassifier when the
        # tenant has both an embedding model configured and at least one intent
        # with current (non-stale) example embeddings. The classifier is only
        # actually invoked by the engine if a rule has an intent condition.
        intent_classifier = self._build_intent_classifier(tenant_config)
        match = await self._engine.evaluate(
            request_data, tenant_config, intent_classifier=intent_classifier
        )
        if not match:
            raise NoRuleMatchedError("No routing rule matched for this request")

        model = tenant_config.models.get(match.target_model)
        if not model:
            raise ModelNotFoundError(
                f"Rule '{match.rule.name}' targets model '{match.target_model}' "
                f"which is not registered for this tenant"
            )
        return model, match

    async def complete(
        self,
        tenant_id: UUID,
        request_data: dict,
    ) -> Any:
        """Full pipeline: load config → resolve model → call litellm (or dispatch to worker)."""
        tenant_config = await self.load_tenant_config(tenant_id)
        model, rule_match = await self.resolve_model(tenant_config, request_data)

        # Executor models route to a worker instead of litellm
        if model.provider == "executor":
            return await self._execute_via_worker(tenant_id, request_data, model, rule_match)

        if litellm is None:
            raise ChatError(
                "litellm is not installed",
                code="dependency_missing",
                status_code=500,
            )

        # Decrypt provider API key
        api_key: str | None = None
        if model.api_key_encrypted and self._encryption_key:
            try:
                api_key = decrypt_value(model.api_key_encrypted, self._encryption_key)
            except Exception as exc:
                logger.error(
                    "api_key_decrypt_failed",
                    model=model.litellm_model,
                    provider=model.provider,
                )
                raise ChatError(
                    "Failed to decrypt API key for model",
                    code="decryption_failed",
                    status_code=500,
                ) from exc

        # Build litellm call kwargs
        litellm_kwargs: dict[str, Any] = {
            "model": model.litellm_model,
            "messages": request_data["messages"],
        }
        if api_key:
            litellm_kwargs["api_key"] = api_key
        if model.api_base:
            litellm_kwargs["api_base"] = model.api_base

        # Pass through optional OpenAI params
        for param in (
            "temperature",
            "max_tokens",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "stop",
            "n",
            "tools",
            "tool_choice",
            "response_format",
        ):
            if param in request_data:
                litellm_kwargs[param] = request_data[param]

        # Extra params from model config (never allow overriding request-critical fields)
        _protected = {"model", "messages", "stream", "api_key", "api_base"}
        if model.extra_params:
            for k, v in model.extra_params.items():
                if k not in _protected:
                    litellm_kwargs[k] = v

        stream = request_data.get("stream", False)
        litellm_kwargs["stream"] = stream

        response = await litellm.acompletion(**litellm_kwargs)

        # Fire-and-forget: log routing decision + budget tracking
        task = asyncio.create_task(
            asyncio.wait_for(
                self._log_request(tenant_id, rule_match, request_data, model),
                timeout=executor_settings.routing_log_timeout_seconds,
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._on_background_done)

        return response

    async def _execute_via_worker(
        self,
        tenant_id: UUID,
        request_data: dict,
        model: TenantModel,
        rule_match: RuleMatch | None,
    ) -> dict[str, Any]:
        """Dispatch the chat request to an executor worker and await its result."""
        if self._redis is None:
            raise ChatError(
                "Redis not configured — executor dispatch requires Redis",
                code="redis_missing",
                status_code=503,
            )

        prompt = _last_user_message(request_data.get("messages", []))
        if not prompt:
            raise ChatError("Executor models require a user message", code="no_user_message")

        lm = model.litellm_model
        executor_type = lm.split("/", 1)[-1] if "/" in lm else lm
        extra = model.extra_params or {}
        pinned_worker_id = extra.get("worker_id")

        # Create task, pick worker, mark dispatched — single connection +
        # transaction for atomicity.
        async with self._pool.acquire() as conn, conn.transaction():
            task_row = await conn.fetchrow(
                _executor_sql.query("create_task"), tenant_id, executor_type, prompt
            )
            worker_id = await self._pick_worker(conn, tenant_id, pinned_worker_id)
            if worker_id is None:
                raise ChatError(
                    "No available worker for this model — run the worker machine "
                    "(Models → Install Worker).",
                    code="no_worker_available",
                    status_code=503,
                )
            task_id = task_row["id"]
            await conn.execute(_executor_sql.query("update_task_dispatched"), task_id, worker_id)

        from bsgateway.streams import RedisStreamManager

        dispatcher = WorkerDispatcher(RedisStreamManager(self._redis))
        await dispatcher.dispatch_task(worker_id, task_id, executor_type, prompt)

        final_row = await self._await_task_completion(
            task_id,
            tenant_id,
            timeout_seconds=int(
                extra.get("timeout_seconds", executor_settings.worker_default_timeout_seconds)
            ),
        )

        if final_row["status"] == "failed":
            raise ChatError(
                final_row["error_message"] or "Executor failed",
                code="executor_failed",
                status_code=502,
            )

        log_task = asyncio.create_task(
            asyncio.wait_for(
                self._log_request(tenant_id, rule_match, request_data, model),
                timeout=executor_settings.routing_log_timeout_seconds,
            )
        )
        self._background_tasks.add(log_task)
        log_task.add_done_callback(self._on_background_done)

        return {
            "id": f"exec-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "model": model.model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": final_row["output"] or ""},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    async def _pick_worker(
        self,
        conn: asyncpg.Connection,
        tenant_id: UUID,
        pinned_worker_id: str | None,
    ) -> UUID | None:
        """Return the pinned worker if still active, else any available one."""
        if pinned_worker_id:
            # Pinned workers are accepted even with a stale heartbeat — the
            # user explicitly registered this worker as the routable model.
            row = await conn.fetchrow(
                "SELECT id FROM workers WHERE id = $1 AND tenant_id = $2 AND is_active = TRUE",
                UUID(str(pinned_worker_id)),
                tenant_id,
            )
            if row:
                return row["id"]
        row = await conn.fetchrow(_executor_sql.query("find_available_worker"), tenant_id)
        return row["id"] if row else None

    async def _await_task_completion(
        self,
        task_id: UUID,
        tenant_id: UUID,
        timeout_seconds: int,
        poll_interval: float | None = None,
    ) -> asyncpg.Record:
        """Poll executor_tasks until status transitions out of pending/dispatched.

        TODO: replace DB polling with a Redis pub/sub channel the worker
        /result handler writes to (e.g. ``task:{id}:done``). Cuts up to
        ``timeout/poll_interval`` DB hits per task under load.
        """
        if poll_interval is None:
            poll_interval = executor_settings.worker_poll_interval_seconds
        elapsed = 0.0
        while elapsed < timeout_seconds:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(_executor_sql.query("get_task"), task_id, tenant_id)
            if row and row["status"] in ("done", "failed"):
                return row
        raise ChatError(
            f"Executor task timed out after {timeout_seconds}s",
            code="executor_timeout",
            status_code=504,
        )

    def _on_background_done(self, task: asyncio.Task) -> None:
        """Clean up background task and log any unhandled errors."""
        self._background_tasks.discard(task)
        if not task.cancelled():
            exc = task.exception()
            if exc:
                exc_tuple = (type(exc), exc, exc.__traceback__)
                logger.warning("background_task_failed", exc_info=exc_tuple)

    async def _log_request(
        self,
        tenant_id: UUID,
        rule_match: RuleMatch | None,
        request_data: dict,
        model: TenantModel,
    ) -> None:
        """Log routing decision to DB and update budget tracker.

        All persistence flows through ``RoutingLogsRepository`` which
        forces ``tenant_id`` onto every routing_logs query — see C2 in
        the BSVibe Ecosystem Audit.
        """
        try:
            ctx = EvaluationContext.from_request(request_data)
            rule_id = uuid.UUID(rule_match.rule.id) if rule_match else None
            repo = RoutingLogsRepository(self._pool)

            await repo.insert_routing_log(
                tenant_id=tenant_id,
                rule_id=rule_id,
                user_text=ctx.user_text[:2000],
                system_prompt=ctx.system_prompt[:2000],
                features={
                    "token_count": ctx.estimated_tokens,
                    "conversation_turns": ctx.conversation_turns,
                    "code_block_count": 0,
                    "code_lines": 0,
                    "has_error_trace": ctx.has_error_trace,
                    "tool_count": ctx.tool_count,
                },
                tier="rule" if rule_match else "direct",
                strategy="rule_engine",
                score=rule_match.rule.priority if rule_match else None,
                original_model=request_data.get("model", "auto"),
                resolved_model=model.litellm_model,
                embedding=None,
                nexus_task_type=None,
                nexus_priority=None,
                nexus_complexity_hint=None,
                decision_source="rule_engine",
            )
        except (ConnectionError, TimeoutError, OSError):
            logger.warning("routing_log_failed", exc_info=True)
        except Exception:
            logger.error("routing_log_unexpected_error", exc_info=True)

        # Budget tracking
        if self._redis:
            try:
                from bsgateway.rules.budget import BudgetTracker

                tracker = BudgetTracker(self._redis)
                await tracker.increment_request_count(str(tenant_id))
            except (ConnectionError, TimeoutError, OSError):
                logger.warning("budget_tracking_failed", exc_info=True)
            except Exception:
                logger.error("budget_tracking_unexpected_error", exc_info=True)


class ChatError(Exception):
    """Base class for chat completion errors."""

    def __init__(self, message: str, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ModelNotFoundError(ChatError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="model_not_found", status_code=400)


class NoRuleMatchedError(ChatError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="no_rule_matched", status_code=400)
