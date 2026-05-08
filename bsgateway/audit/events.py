"""Phase 3 / TASK-006 — BSGateway-local audit event catalog.

These subclasses extend :class:`bsvibe_audit.events.base.AuditEventBase`
with BSGateway-specific ``DEFAULT_EVENT_TYPE`` literals. They live here
(not upstream in ``bsvibe_audit.events.gateway``) because BSGateway is
the only producer — keeping the catalog local lets us add events
without a cross-repo bump.

Convention:
* event_type names follow ``gateway.<scope>.<verb>``
* ``data`` payload carries non-secret fields only (no ``litellm_params``,
  no provider tokens, no full request bodies)
* emit sites use ``bsgateway.audit_publisher.emit_event(state, EventClass(...))``
"""

from __future__ import annotations

from typing import ClassVar

from bsvibe_audit.events.base import AuditEventBase


class ModelCreated(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.model.created"


class ModelUpdated(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.model.updated"


class ModelDeleted(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.model.deleted"


class ModelHidden(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.model.hidden"


class RoutingRuleCreated(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.routing.rule.created"


class RoutingRuleUpdated(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.routing.rule.updated"


class RoutingRuleDeleted(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.routing.rule.deleted"


class RoutingIntentCreated(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.routing.intent.created"


class RoutingIntentUpdated(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.routing.intent.updated"


class RoutingIntentDeleted(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.routing.intent.deleted"


class RoutingPresetApplied(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.routing.preset.applied"


class TenantCreated(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.tenant.created"


class TenantUpdated(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.tenant.updated"


class TenantDeactivated(AuditEventBase):
    DEFAULT_EVENT_TYPE: ClassVar[str] = "gateway.tenant.deactivated"


__all__ = [
    "ModelCreated",
    "ModelDeleted",
    "ModelHidden",
    "ModelUpdated",
    "RoutingIntentCreated",
    "RoutingIntentDeleted",
    "RoutingIntentUpdated",
    "RoutingPresetApplied",
    "RoutingRuleCreated",
    "RoutingRuleDeleted",
    "RoutingRuleUpdated",
    "TenantCreated",
    "TenantDeactivated",
    "TenantUpdated",
]
