from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from bsgateway.api.deps import GatewayAuthContext, get_pool, require_tenant_access
from bsgateway.routing.repository import RoutingLogsRepository

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/tenants/{tenant_id}/usage",
    tags=["usage"],
)


class ModelUsage(BaseModel):
    requests: int
    tokens: int


class DailyUsage(BaseModel):
    date: str
    requests: int
    tokens: int


class UsageResponse(BaseModel):
    total_requests: int
    total_tokens: int
    by_model: dict[str, ModelUsage]
    by_rule: dict[str, int]
    daily_breakdown: list[DailyUsage]


def _parse_period(
    period: str,
    from_date: date | None,
    to_date: date | None,
) -> tuple[datetime, datetime]:
    """Convert period + optional dates into a (start, end) UTC datetime range."""
    today = datetime.now(UTC).date()
    if from_date and to_date:
        return (
            datetime.combine(from_date, datetime.min.time(), tzinfo=UTC),
            datetime.combine(to_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
        )
    if period == "day":
        start = today
    elif period == "week":
        start = today - timedelta(days=7)
    elif period == "month":
        start = today - timedelta(days=30)
    else:
        start = today
    return (
        datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
    )


@router.get("", response_model=UsageResponse, summary="Get usage statistics")
async def get_usage(
    tenant_id: UUID,
    request: Request,
    auth: GatewayAuthContext = Depends(require_tenant_access),
    period: str = Query("day", pattern="^(day|week|month)$"),
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
) -> UsageResponse:
    """Get usage statistics for a tenant."""
    pool = get_pool(request)
    start, end = _parse_period(period, from_date, to_date)
    repo = RoutingLogsRepository(pool)

    total_row, model_rows, rule_rows = await asyncio.gather(
        repo.usage_total(tenant_id, start, end),
        repo.usage_by_model(tenant_id, start, end),
        repo.usage_by_rule(tenant_id, start, end),
    )

    total_requests = total_row["total_requests"] if total_row else 0
    total_tokens = total_row["total_tokens"] if total_row else 0

    # Aggregate by model
    by_model: dict[str, dict[str, int]] = defaultdict(lambda: {"requests": 0, "tokens": 0})
    daily: dict[str, dict[str, int]] = defaultdict(lambda: {"requests": 0, "tokens": 0})

    for row in model_rows:
        model_name = row["resolved_model"] or "unknown"
        by_model[model_name]["requests"] += row["requests"]
        by_model[model_name]["tokens"] += row["tokens"]

        day_str = str(row["day"])
        daily[day_str]["requests"] += row["requests"]
        daily[day_str]["tokens"] += row["tokens"]

    by_model_resp = {
        k: ModelUsage(requests=v["requests"], tokens=v["tokens"]) for k, v in by_model.items()
    }

    # Aggregate by rule
    by_rule = {(row["rule_name"] or str(row["rule_id"])): row["requests"] for row in rule_rows}

    daily_breakdown = sorted(
        [
            DailyUsage(date=day, requests=v["requests"], tokens=v["tokens"])
            for day, v in daily.items()
        ],
        key=lambda d: d.date,
    )

    return UsageResponse(
        total_requests=total_requests,
        total_tokens=total_tokens,
        by_model=by_model_resp,
        by_rule=by_rule,
        daily_breakdown=daily_breakdown,
    )


@router.get("/sparklines", summary="Per-model daily request counts for sparkline charts")
async def get_sparklines(
    tenant_id: UUID,
    request: Request,
    auth: GatewayAuthContext = Depends(require_tenant_access),
    days: int = Query(7, ge=1, le=90),
) -> dict[str, list[int]]:
    """Return per-model per-day request counts for the last ``days`` days.

    Combines LLM traffic (``routing_logs.resolved_model``) and executor
    traffic (``executor_tasks`` joined with ``workers.name``). Returns a
    fixed-length array per model, where index ``0`` is the oldest day
    (``days-1`` days ago) and index ``days-1`` is today.

    Models with zero activity in the window are omitted — the caller
    should treat absence as "all zeros".
    """
    pool = get_pool(request)
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    repo = RoutingLogsRepository(pool)

    async def _fetch_exec():
        # executor_tasks already enforces tenant_id at the SQL level — kept
        # inline because it lives in the executor schema rather than
        # routing_logs. The WHERE clause below is the contract test.
        async with pool.acquire() as conn:
            return await conn.fetch(
                "SELECT DATE(t.created_at) AS day, w.name AS resolved_model, "
                "       COUNT(*) AS requests "
                "FROM executor_tasks t JOIN workers w ON t.worker_id = w.id "
                "WHERE t.tenant_id = $1 AND t.created_at >= $2 AND t.created_at < $3 "
                "GROUP BY DATE(t.created_at), w.name",
                tenant_id,
                start_dt,
                end_dt,
            )

    llm_rows, exec_rows = await asyncio.gather(
        repo.usage_by_model(tenant_id, start_dt, end_dt), _fetch_exec()
    )

    day_index = {start + timedelta(days=i): i for i in range(days)}
    result: dict[str, list[int]] = {}
    for row in list(llm_rows) + list(exec_rows):
        name = row["resolved_model"]
        if not name:
            continue
        idx = day_index.get(row["day"])
        if idx is None:
            continue
        arr = result.setdefault(name, [0] * days)
        arr[idx] += int(row["requests"])

    return result
