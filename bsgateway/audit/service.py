from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from bsgateway.audit.repository import AuditRepository

logger = structlog.get_logger(__name__)


class AuditService:
    """Fire-and-forget audit logging service."""

    def __init__(self, repo: AuditRepository) -> None:
        self._repo = repo

    async def record(
        self,
        tenant_id: UUID,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record an audit log entry. Swallows exceptions."""
        try:
            await self._repo.record(
                tenant_id=tenant_id,
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
            )
            logger.debug(
                "audit_recorded",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
            )
        except Exception:
            logger.warning(
                "audit_record_failed",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                tenant_id=str(tenant_id),
                exc_info=True,
            )
