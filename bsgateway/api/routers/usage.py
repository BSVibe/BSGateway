from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from bsgateway.api.deps import GatewayAuthContext, get_pool, require_tenant_access
from bsgateway.routing.collector import SqlLoader

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/tenants/{tenant_id}/usage",
    tags=["usage"],
)

_sql = SqlLoader()


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

    async def _fetch_total():
        async with pool.acquire() as conn:
            return await conn.fetchrow(_sql.query("usage_total"), tenant_id, start, end)

    async def _fetch_models():
        async with pool.acquire() as conn:
            return await conn.fetch(_sql.query("usage_by_model"), tenant_id, start, end)

    async def _fetch_rules():
        async with pool.acquire() as conn:
            return await conn.fetch(_sql.query("usage_by_rule"), tenant_id, start, end)

    total_row, model_rows, rule_rows = await asyncio.gather(
        _fetch_total(), _fetch_models(), _fetch_rules()
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
