from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
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
from bsgateway.executor.dispatcher import WorkerDispatcher, done_channel, stream_channel
from bsgateway.executor.sql_loader import ExecutorSqlLoader
from bsgateway.routing.classifiers.base import extract_system_prompt
from bsgateway.routing.collector import SqlLoader
from bsgateway.routing.constants import LOG_TEXT_MAX_CHARS
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

    from bsgateway.supervisor.client import BSupervisorClient, RunMetadata

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
        supervisor: BSupervisorClient | None = None,
    ) -> None:
        self._pool = pool
        self._encryption_key = encryption_key
        self._redis = redis
        self._engine = RuleEngine()
        self._background_tasks: set[asyncio.Task] = (
            background_tasks if background_tasks is not None else set()
        )
        self._supervisor = supervisor

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

        # Build litellm call kwargs.
        #
        # Sprint 0 follow-up (docs/TODO.md S1): plumb tenant_id into the
        # litellm metadata so the BSGateway proxy hook (which reads
        # ``data["metadata"]["tenant_id"]``) can scope its routing_logs
        # write. Pre-fix the hook saw no tenant and skipped recording.
        request_metadata = dict(request_data.get("metadata") or {})
        request_metadata["tenant_id"] = str(tenant_id)
        litellm_kwargs: dict[str, Any] = {
            "model": model.litellm_model,
            "messages": request_data["messages"],
            "metadata": request_metadata,
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

        # Extra params from model config (never allow overriding request-critical fields).
        # ``metadata`` is protected because we just stamped tenant_id into
        # it — letting per-model extra_params clobber it would silently
        # un-scope routing_logs (regression of C2).
        _protected = {"model", "messages", "stream", "api_key", "api_base", "metadata"}
        if model.extra_params:
            for k, v in model.extra_params.items():
                if k not in _protected:
                    litellm_kwargs[k] = v

        stream = request_data.get("stream", False)
        litellm_kwargs["stream"] = stream

        run_meta = self._run_metadata(request_metadata, resolved_model=model.litellm_model)
        if self._supervisor is not None and run_meta is not None:
            pre = await self._supervisor.run_pre(run_meta)
            if pre.blocked:
                raise ChatError(
                    pre.reason or "blocked by BSupervisor policy",
                    code="bsupervisor_blocked",
                    status_code=403,
                )

        try:
            response = await litellm.acompletion(**litellm_kwargs)
        except Exception:
            if self._supervisor is not None and run_meta is not None:
                await self._supervisor.run_post(
                    run_meta,
                    status="error",
                )
            raise

        if self._supervisor is not None and run_meta is not None:
            usage = getattr(response, "usage", None)
            await self._supervisor.run_post(
                run_meta,
                status="success",
                tokens_in=getattr(usage, "prompt_tokens", None) if usage is not None else None,
                tokens_out=getattr(usage, "completion_tokens", None) if usage is not None else None,
            )

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

    @staticmethod
    def _run_metadata(metadata: dict[str, Any], *, resolved_model: str) -> RunMetadata | None:
        from bsgateway.supervisor.client import RunMetadata

        return RunMetadata.from_request_metadata(metadata, resolved_model=resolved_model)

    async def _execute_via_worker(
        self,
        tenant_id: UUID,
        request_data: dict,
        model: TenantModel,
        rule_match: RuleMatch | None,
    ) -> Any:
        """Dispatch the chat request to an executor worker.

        For ``stream=False`` returns a single ``chat.completion`` dict
        (built from the worker's ``executor_tasks`` final row). For
        ``stream=True`` returns an async generator yielding incremental
        ``chat.completion.chunk`` dicts that the chat router wraps as
        SSE. Both paths use Redis pub/sub instead of polling — chunks
        flow on ``task:{id}:stream`` and completion on
        ``task:{id}:done`` (TODO E1 closed via the same channel).
        """
        if self._redis is None:
            raise ChatError(
                "Redis not configured — executor dispatch requires Redis",
                code="redis_missing",
                status_code=503,
            )

        prompt = _last_user_message(request_data.get("messages", []))
        if not prompt:
            raise ChatError("Executor models require a user message", code="no_user_message")
        system_prompt = extract_system_prompt(request_data)

        lm = model.litellm_model
        executor_type = lm.split("/", 1)[-1] if "/" in lm else lm
        extra = model.extra_params or {}
        pinned_worker_id = extra.get("worker_id")
        timeout_seconds = int(
            extra.get("timeout_seconds", executor_settings.worker_default_timeout_seconds)
        )

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

        sm = RedisStreamManager(self._redis)
        # Subscribe BEFORE dispatch so we can't miss the first chunk —
        # pub/sub is lossy. The subscription is held inside the iterator
        # the gateway router consumes so cleanup happens on stream close.
        if request_data.get("stream"):
            return self._stream_worker_response(
                sm,
                worker_id=worker_id,
                task_id=task_id,
                executor_type=executor_type,
                prompt=prompt,
                system=system_prompt,
                tenant_id=tenant_id,
                request_data=request_data,
                model=model,
                rule_match=rule_match,
                timeout_seconds=timeout_seconds,
            )

        dispatcher = WorkerDispatcher(sm)
        await dispatcher.dispatch_task(
            worker_id, task_id, executor_type, prompt, system=system_prompt
        )

        final_row = await self._await_task_completion(
            task_id,
            tenant_id,
            timeout_seconds=timeout_seconds,
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

    async def _stream_worker_response(
        self,
        stream_manager: Any,
        *,
        worker_id: UUID,
        task_id: UUID,
        executor_type: str,
        prompt: str,
        system: str,
        tenant_id: UUID,
        request_data: dict,
        model: TenantModel,
        rule_match: RuleMatch | None,
        timeout_seconds: int,
    ) -> AsyncIterator[dict[str, Any]]:
        """Async generator: dispatch then forward worker chunks as OpenAI chunks.

        Subscribes to ``task:{id}:stream`` before dispatch to avoid
        missing the first chunk (Redis pub/sub is lossy). Each worker
        chunk becomes a ``chat.completion.chunk`` with ``delta.content``;
        the terminal chunk carries ``finish_reason``.
        """
        chan = stream_channel(task_id)
        sub_iter = await stream_manager.subscribe_pubsub(chan, timeout=timeout_seconds)

        dispatcher = WorkerDispatcher(stream_manager)
        await dispatcher.dispatch_task(worker_id, task_id, executor_type, prompt, system=system)

        completion_id = f"exec-{uuid.uuid4().hex[:24]}"
        created = int(time.time())

        def _make_chunk(delta: str = "", finish_reason: str | None = None) -> dict[str, Any]:
            choice: dict[str, Any] = {
                "index": 0,
                "delta": {"content": delta} if delta else {},
                "finish_reason": finish_reason,
            }
            return {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model.model_name,
                "choices": [choice],
            }

        # OpenAI's first stream chunk conventionally carries the role.
        first_chunk = _make_chunk()
        first_chunk["choices"][0]["delta"] = {"role": "assistant"}
        yield first_chunk

        terminal_error: str | None = None
        try:
            async for msg in sub_iter:
                delta = msg.get("delta") or ""
                done = bool(msg.get("done"))
                err = msg.get("error")
                if delta:
                    yield _make_chunk(delta=delta)
                if err:
                    terminal_error = err
                if done:
                    break
        finally:
            aclose = getattr(sub_iter, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    pass

        if terminal_error:
            yield _make_chunk(finish_reason="stop")
            yield {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model.model_name,
                "choices": [],
                "error": {
                    "message": terminal_error,
                    "type": "executor_error",
                    "code": "executor_failed",
                },
            }
        else:
            yield _make_chunk(finish_reason="stop")

        log_task = asyncio.create_task(
            asyncio.wait_for(
                self._log_request(tenant_id, rule_match, request_data, model),
                timeout=executor_settings.routing_log_timeout_seconds,
            )
        )
        self._background_tasks.add(log_task)
        log_task.add_done_callback(self._on_background_done)

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
        """Wait for the worker to publish on ``task:{id}:done`` then read the row.

        Replaces the previous 1 Hz DB polling loop. The worker publishes
        a single completion message on ``task:{id}:done`` after writing
        the final ``executor_tasks`` row; we then read the row exactly
        once. On Redis outage / missed publish we fall back to a single
        DB read at timeout so callers never hang silently.
        """
        if self._redis is None:
            raise ChatError(
                "Redis not configured — executor dispatch requires Redis",
                code="redis_missing",
                status_code=503,
            )

        from bsgateway.streams import RedisStreamManager

        sm = RedisStreamManager(self._redis)
        chan = done_channel(task_id)
        try:
            sub_iter = await sm.subscribe_pubsub(chan, timeout=timeout_seconds)
            async for _msg in sub_iter:
                # The worker only publishes once when the executor_tasks row
                # has been written; read it back for the canonical record.
                async with self._pool.acquire() as conn:
                    row = await conn.fetchrow(_executor_sql.query("get_task"), task_id, tenant_id)
                if row and row["status"] in ("done", "failed"):
                    return row
                # Worker published before its own /result write landed —
                # rare race; loop and re-read on next message.
        except Exception as exc:
            logger.warning("await_pubsub_failed", task_id=str(task_id), error=str(exc))

        # Fallback: one final DB read in case the publish was missed.
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_executor_sql.query("get_task"), task_id, tenant_id)
        if row and row["status"] in ("done", "failed"):
            return row
        # poll_interval kept for backward-compat callers; unused now.
        _ = poll_interval
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
                user_text=ctx.user_text[:LOG_TEXT_MAX_CHARS],
                system_prompt=ctx.system_prompt[:LOG_TEXT_MAX_CHARS],
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
