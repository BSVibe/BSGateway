"""Execute endpoint — submit async executor tasks and poll results.

DATA-PLANE: the executor dispatch path is a core gateway function, the
async sibling of ``POST /chat/completions``. All three routes here
(``POST /execute``, ``GET /tasks/{id}``, ``GET /tasks``) are deliberately
gated only by tenant-scoped authentication (``get_auth_context``) — NOT
by a per-resource ``require_permission`` gate. The permission matrix row
``bsgateway.execute.write`` exists for a future control-plane execute
admin surface (e.g. quota / executor-config management); it is NOT
applied to the data-plane dispatch routes below. Any authenticated
tenant member may submit and read their own tasks.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from bsgateway.api.deps import (
    GatewayAuthContext,
    get_auth_context,
    get_pool,
)
from bsgateway.executor.dispatcher import WorkerDispatcher
from bsgateway.executor.sql_loader import ExecutorSqlLoader
from bsgateway.streams import RedisStreamManager

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["execute"])
_sql = ExecutorSqlLoader()


# ── Schemas ─────────────────────────────────────────────────────────


class ExecuteRequest(BaseModel):
    executor_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Executor to use (e.g., 'claude_code', 'codex')",
    )
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="The prompt/instruction to execute",
    )


class ExecuteResponse(BaseModel):
    task_id: UUID
    status: str


class TaskResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    executor_type: str
    prompt: str
    status: str
    worker_id: UUID | None = None
    output: str | None = None
    error_message: str | None = None
    created_at: Any = None
    updated_at: Any = None


# ── Helpers ─────────────────────────────────────────────────────────


def _get_dispatcher(request: Request) -> WorkerDispatcher:
    sm: RedisStreamManager | None = getattr(request.app.state, "stream_manager", None)
    if sm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis not available for task dispatch",
        )
    return WorkerDispatcher(sm)


# ── Endpoints ───────────────────────────────────────────────────────


@router.post(
    "/execute",
    response_model=ExecuteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an executor task",
)
async def submit_task(
    body: ExecuteRequest,
    request: Request,
    auth: GatewayAuthContext = Depends(get_auth_context),
) -> ExecuteResponse:
    """Create a task and dispatch it to an available worker."""
    pool: asyncpg.Pool = get_pool(request)

    # Create the task
    async with pool.acquire() as conn:
        task_row = await conn.fetchrow(
            _sql.query("create_task"),
            auth.tenant_id,
            body.executor_type,
            body.prompt,
        )

    task_id = task_row["id"]

    # Find an available worker and dispatch
    async with pool.acquire() as conn:
        worker_row = await conn.fetchrow(
            _sql.query("find_available_worker"),
            auth.tenant_id,
        )

    if not worker_row:
        logger.warning("no_worker_available", tenant_id=str(auth.tenant_id))
        return ExecuteResponse(task_id=task_id, status="pending")

    dispatcher = _get_dispatcher(request)
    await dispatcher.dispatch_task(
        worker_id=worker_row["id"],
        task_id=task_id,
        executor_type=body.executor_type,
        prompt=body.prompt,
    )

    # Mark as dispatched
    async with pool.acquire() as conn:
        await conn.execute(
            _sql.query("update_task_dispatched"),
            task_id,
            worker_row["id"],
        )

    logger.info("task_submitted", task_id=str(task_id), worker_id=str(worker_row["id"]))
    return ExecuteResponse(task_id=task_id, status="dispatched")


@router.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    summary="Get task status and result",
)
async def get_task(
    task_id: UUID,
    request: Request,
    auth: GatewayAuthContext = Depends(get_auth_context),
) -> TaskResponse:
    """Retrieve the current status and output of a task."""
    pool = get_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            _sql.query("get_task"),
            task_id,
            auth.tenant_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(**dict(row))


@router.get(
    "/tasks",
    response_model=list[TaskResponse],
    summary="List tasks",
)
async def list_tasks(
    request: Request,
    auth: GatewayAuthContext = Depends(get_auth_context),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[TaskResponse]:
    """List executor tasks for the authenticated tenant."""
    pool = get_pool(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _sql.query("list_tasks"),
            auth.tenant_id,
            limit,
            offset,
        )
    return [TaskResponse(**dict(r)) for r in rows]
