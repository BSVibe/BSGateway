from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from bsgateway.core.security import decrypt_value
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

_tenant_sql = SqlLoader()
_rules_sql = SqlLoader()
_log_sql = SqlLoader()


def _parse_value(raw: Any) -> Any:
    """Parse JSONB value from DB record."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
    return raw


def _safe_json_loads(raw: str | dict | None) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


class ChatService:
    """Thin orchestrator: auth → rule evaluation → litellm delegation."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        encryption_key: bytes,
        redis: Redis | None = None,
    ) -> None:
        self._pool = pool
        self._encryption_key = encryption_key
        self._redis = redis
        self._engine = RuleEngine()
        self._background_tasks: set[asyncio.Task] = set()

    async def load_tenant_config(self, tenant_id: UUID) -> TenantConfig:
        """Batch-load rules + conditions + models for a tenant (3 queries)."""
        async with self._pool.acquire() as conn:
            # 1. Active rules
            rule_rows = await conn.fetch(
                _rules_sql.query("list_rules"),
                tenant_id,
            )
            # 2. Conditions for all of tenant's rules (batch)
            cond_rows = await conn.fetch(
                _rules_sql.query("list_conditions_for_tenant"),
                tenant_id,
            )
            # 3. Active models with encrypted keys
            model_rows = await conn.fetch(
                _tenant_sql.query("list_active_models_with_keys"),
                tenant_id,
            )
            # 4. Tenant settings
            tenant_row = await conn.fetchrow(
                _tenant_sql.query("get_tenant_by_id"),
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
                    value=_parse_value(c["value"]),
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
                extra_params=_safe_json_loads(m["extra_params"]),
            )

        settings = _safe_json_loads(tenant_row["settings"]) if tenant_row else {}

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
        import litellm

        tenant_config = await self.load_tenant_config(tenant_id)

        model, rule_match = await self.resolve_model(tenant_config, request_data)

        # Decrypt provider API key
        api_key: str | None = None
        if model.api_key_encrypted and self._encryption_key:
            api_key = decrypt_value(model.api_key_encrypted, self._encryption_key)

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
            "temperature", "max_tokens", "top_p", "frequency_penalty",
            "presence_penalty", "stop", "n", "tools", "tool_choice",
            "response_format",
        ):
            if param in request_data:
                litellm_kwargs[param] = request_data[param]

        # Extra params from model config
        if model.extra_params:
            litellm_kwargs.update(model.extra_params)

        stream = request_data.get("stream", False)
        litellm_kwargs["stream"] = stream

        response = await litellm.acompletion(**litellm_kwargs)

        # Fire-and-forget: log routing decision + budget tracking
        task = asyncio.create_task(
            self._log_request(tenant_id, rule_match, request_data, model)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return response

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
                    _log_sql.query("insert_routing_log_with_tenant"),
                    tenant_id,                   # $1
                    rule_id,                     # $2
                    ctx.user_text[:2000],         # $3 truncate
                    ctx.system_prompt[:2000],     # $4
                    ctx.estimated_tokens,         # $5
                    ctx.conversation_turns,       # $6
                    0,                            # $7 code_block_count
                    0,                            # $8 code_lines
                    ctx.has_error_trace,          # $9
                    ctx.tool_count,               # $10
                    "rule" if rule_match else "direct",  # $11 tier
                    "rule_engine",                # $12 strategy
                    rule_match.rule.priority if rule_match else None,  # $13
                    request_data.get("model", "auto"),  # $14
                    model.litellm_model,          # $15
                )
        except Exception:
            logger.warning("routing_log_failed", exc_info=True)

        # Budget tracking
        if self._redis:
            try:
                from bsgateway.rules.budget import BudgetTracker

                tracker = BudgetTracker(self._redis)
                await tracker.increment_request_count(str(tenant_id))
            except Exception:
                logger.warning("budget_tracking_failed", exc_info=True)


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
