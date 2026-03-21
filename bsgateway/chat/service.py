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
from bsgateway.core.utils import parse_jsonb_value, safe_json_loads
from bsgateway.routing.collector import SqlLoader
from bsgateway.rules.engine import RuleEngine
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
        """Batch-load rules + conditions + models for a tenant (3 queries)."""
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

        return TenantConfig(
            tenant_id=str(tenant_id),
            slug=tenant_row["slug"] if tenant_row else "",
            models=models,
            rules=rules,
            settings=settings,
        )

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

        # Rule engine evaluation
        match = await self._engine.evaluate(request_data, tenant_config)
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
        """Full pipeline: load config → resolve model → call litellm."""
        if litellm is None:
            raise ChatError(
                "litellm is not installed",
                code="dependency_missing",
                status_code=500,
            )

        tenant_config = await self.load_tenant_config(tenant_id)

        model, rule_match = await self.resolve_model(tenant_config, request_data)

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

        # Fire-and-forget: log routing decision + budget tracking (30s timeout)
        task = asyncio.create_task(
            asyncio.wait_for(
                self._log_request(tenant_id, rule_match, request_data, model),
                timeout=30.0,
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._on_background_done)

        return response

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
        """Log routing decision to DB and update budget tracker."""
        try:
            ctx = EvaluationContext.from_request(request_data)
            rule_id = uuid.UUID(rule_match.rule.id) if rule_match else None

            async with self._pool.acquire() as conn:
                await conn.execute(
                    _sql.query("insert_routing_log_with_tenant"),
                    tenant_id,  # $1
                    rule_id,  # $2
                    ctx.user_text[:2000],  # $3 truncate
                    ctx.system_prompt[:2000],  # $4
                    ctx.estimated_tokens,  # $5
                    ctx.conversation_turns,  # $6
                    0,  # $7 code_block_count
                    0,  # $8 code_lines
                    ctx.has_error_trace,  # $9
                    ctx.tool_count,  # $10
                    "rule" if rule_match else "direct",  # $11 tier
                    "rule_engine",  # $12 strategy
                    rule_match.rule.priority if rule_match else None,  # $13
                    request_data.get("model", "auto"),  # $14
                    model.litellm_model,  # $15
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
