"""MCP service layer — orchestrates repository calls for MCP tool handlers."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import structlog

from bsgateway.core.cache import CacheManager
from bsgateway.core.utils import parse_jsonb_value
from bsgateway.mcp.schemas import (
    MCPCondition,
    MCPCostReport,
    MCPModelResponse,
    MCPRuleResponse,
    MCPSimulateResponse,
    MCPUsageStats,
)
from bsgateway.routing.collector import SqlLoader
from bsgateway.rules.engine import RuleEngine
from bsgateway.rules.models import (
    EvaluationContext,
    RoutingRule,
    RuleCondition,
    TenantConfig,
)
from bsgateway.rules.repository import RulesRepository
from bsgateway.tenant.repository import TenantRepository

logger = structlog.get_logger(__name__)

_usage_sql = SqlLoader()


def _period_range(period: str) -> tuple[datetime, datetime]:
    """Convert a period string to (start, end) UTC datetimes."""
    today = datetime.now(UTC).date()
    if period == "week":
        start = today - timedelta(days=7)
    elif period == "month":
        start = today - timedelta(days=30)
    else:
        start = today
    return (
        datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
    )


class MCPService:
    """Facade consumed by the MCP router."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        cache: CacheManager | None = None,
    ) -> None:
        self._pool = pool
        self._rules_repo = RulesRepository(pool, cache=cache)
        self._tenant_repo = TenantRepository(pool, cache=cache)

    # -- Rules ---------------------------------------------------------------

    async def list_rules(self, tenant_id: UUID) -> list[MCPRuleResponse]:
        rows = await self._rules_repo.list_rules(tenant_id)
        all_conditions = await self._rules_repo.list_conditions_for_tenant(tenant_id)
        cond_by_rule: dict[UUID, list] = defaultdict(list)
        for c in all_conditions:
            cond_by_rule[c["rule_id"]].append(c)
        return [self._to_rule_response(r, cond_by_rule.get(r["id"], [])) for r in rows]

    async def create_rule(
        self,
        tenant_id: UUID,
        name: str,
        conditions: list[MCPCondition],
        target_model: str,
        priority: int = 0,
        is_default: bool = False,
    ) -> MCPRuleResponse:
        row = await self._rules_repo.create_rule(
            tenant_id=tenant_id,
            name=name,
            priority=priority,
            target_model=target_model,
            is_default=is_default,
        )
        if conditions:
            await self._rules_repo.replace_conditions(
                row["id"],
                [c.model_dump() for c in conditions],
            )
        conds = await self._rules_repo.list_conditions(row["id"])
        return self._to_rule_response(row, conds)

    async def update_rule(
        self,
        rule_id: UUID,
        tenant_id: UUID,
        name: str | None = None,
        conditions: list[MCPCondition] | None = None,
        target_model: str | None = None,
        priority: int | None = None,
        is_default: bool | None = None,
    ) -> MCPRuleResponse | None:
        existing = await self._rules_repo.get_rule(rule_id, tenant_id)
        if not existing:
            return None
        row = await self._rules_repo.update_rule(
            rule_id=rule_id,
            tenant_id=tenant_id,
            name=name or existing["name"],
            priority=priority if priority is not None else existing["priority"],
            is_default=is_default if is_default is not None else existing["is_default"],
            target_model=target_model or existing["target_model"],
        )
        if row is None:
            return None
        if conditions is not None:
            await self._rules_repo.replace_conditions(
                rule_id,
                [c.model_dump() for c in conditions],
            )
        conds = await self._rules_repo.list_conditions(rule_id)
        return self._to_rule_response(row, conds)

    async def delete_rule(self, rule_id: UUID, tenant_id: UUID) -> None:
        await self._rules_repo.delete_rule(rule_id, tenant_id)

    # -- Models --------------------------------------------------------------

    async def list_models(self, tenant_id: UUID) -> list[MCPModelResponse]:
        rows = await self._tenant_repo.list_models(tenant_id)
        return [self._to_model_response(r) for r in rows]

    async def register_model(
        self,
        tenant_id: UUID,
        name: str,
        provider: str,
        config: dict,
    ) -> MCPModelResponse:
        litellm_model = config.get("litellm_model", f"{provider}/{name}")
        api_base = config.get("api_base")
        extra_params = {k: v for k, v in config.items() if k not in ("litellm_model", "api_base")}
        row = await self._tenant_repo.create_model(
            tenant_id=tenant_id,
            model_name=name,
            provider=provider,
            litellm_model=litellm_model,
            api_base=api_base,
            extra_params=extra_params or None,
        )
        return self._to_model_response(row)

    # -- Simulate routing ----------------------------------------------------

    async def simulate_routing(
        self,
        tenant_id: UUID,
        model_hint: str,
        text: str,
    ) -> MCPSimulateResponse:
        rule_rows = await self._rules_repo.list_rules(tenant_id)
        all_conditions = await self._rules_repo.list_conditions_for_tenant(tenant_id)
        cond_by_rule: dict[UUID, list] = defaultdict(list)
        for c in all_conditions:
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

        data = {
            "messages": [{"role": "user", "content": text}],
            "model": model_hint,
        }
        engine = RuleEngine()
        match = await engine.evaluate(
            data,
            TenantConfig(tenant_id=str(tenant_id), slug="", models={}, rules=rules),
        )
        ctx = EvaluationContext.from_request(data)
        return MCPSimulateResponse(
            matched_rule=(
                {"id": match.rule.id, "name": match.rule.name, "priority": match.rule.priority}
                if match
                else None
            ),
            target_model=match.target_model if match else None,
            evaluation_trace=match.trace if match and match.trace else [],
            context={
                "estimated_tokens": ctx.estimated_tokens,
                "conversation_turns": ctx.conversation_turns,
                "has_code_blocks": ctx.has_code_blocks,
                "tool_count": ctx.tool_count,
                "original_model": ctx.original_model,
            },
        )

    # -- Cost / Usage --------------------------------------------------------

    async def get_cost_report(
        self,
        tenant_id: UUID,
        period: str = "day",
    ) -> MCPCostReport:
        start, end = _period_range(period)
        async with self._pool.acquire() as conn:
            total_row = await conn.fetchrow(
                _usage_sql.query("usage_total"),
                tenant_id,
                start,
                end,
            )
            model_rows = await conn.fetch(
                _usage_sql.query("usage_by_model"),
                tenant_id,
                start,
                end,
            )

        by_model: dict[str, dict[str, int]] = defaultdict(lambda: {"requests": 0, "tokens": 0})
        for row in model_rows:
            model_name = row["resolved_model"] or "unknown"
            by_model[model_name]["requests"] += row["requests"]
            by_model[model_name]["tokens"] += row["tokens"]

        return MCPCostReport(
            period=period,
            total_requests=total_row["total_requests"] if total_row else 0,
            total_tokens=total_row["total_tokens"] if total_row else 0,
            by_model=dict(by_model),
        )

    async def get_usage_stats(self, tenant_id: UUID) -> MCPUsageStats:
        start, end = _period_range("month")
        async with self._pool.acquire() as conn:
            total_row = await conn.fetchrow(
                _usage_sql.query("usage_total"),
                tenant_id,
                start,
                end,
            )
            model_rows = await conn.fetch(
                _usage_sql.query("usage_by_model"),
                tenant_id,
                start,
                end,
            )
            rule_rows = await conn.fetch(
                _usage_sql.query("usage_by_rule"),
                tenant_id,
                start,
                end,
            )

        by_model: dict[str, dict[str, int]] = defaultdict(lambda: {"requests": 0, "tokens": 0})
        for row in model_rows:
            model_name = row["resolved_model"] or "unknown"
            by_model[model_name]["requests"] += row["requests"]
            by_model[model_name]["tokens"] += row["tokens"]

        by_rule = {(row["rule_name"] or str(row["rule_id"])): row["requests"] for row in rule_rows}

        return MCPUsageStats(
            total_requests=total_row["total_requests"] if total_row else 0,
            total_tokens=total_row["total_tokens"] if total_row else 0,
            by_model=dict(by_model),
            by_rule=by_rule,
        )

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _to_rule_response(
        row: asyncpg.Record | dict,
        conditions: list[asyncpg.Record | dict],
    ) -> MCPRuleResponse:
        return MCPRuleResponse(
            id=row["id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            priority=row["priority"],
            is_active=row["is_active"],
            is_default=row["is_default"],
            target_model=row["target_model"],
            conditions=[
                {
                    "id": str(c["id"]),
                    "condition_type": c["condition_type"],
                    "field": c["field"],
                    "operator": c["operator"],
                    "value": parse_jsonb_value(c["value"]),
                    "negate": c["negate"],
                }
                for c in conditions
            ],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _to_model_response(row: asyncpg.Record | dict) -> MCPModelResponse:
        return MCPModelResponse(
            id=row["id"],
            tenant_id=row["tenant_id"],
            model_name=row["model_name"],
            provider=row["provider"],
            litellm_model=row["litellm_model"],
            api_base=row.get("api_base"),
            created_at=row["created_at"],
        )
