from __future__ import annotations

import json
from uuid import UUID

import structlog

from bsgateway.presets.models import ModelMapping, PresetApplyResult
from bsgateway.presets.registry import PresetRegistry
from bsgateway.rules.repository import RulesRepository
from bsgateway.tenant.repository import TenantRepository

logger = structlog.get_logger(__name__)

_registry = PresetRegistry()


class PresetService:
    """Apply preset templates to tenants."""

    def __init__(
        self, rules_repo: RulesRepository, tenant_repo: TenantRepository,
    ) -> None:
        self._repo = rules_repo
        self._tenant_repo = tenant_repo

    async def apply_preset(
        self,
        tenant_id: UUID,
        preset_name: str,
        model_mapping: ModelMapping,
    ) -> PresetApplyResult:
        """Apply a preset template to a tenant.

        Creates intents, examples, and rules based on the preset,
        mapping abstract model levels to concrete model names.
        All DB operations run in a single transaction for atomicity.
        """
        preset = _registry.get(preset_name)
        if not preset:
            raise ValueError(f"Unknown preset: {preset_name}")

        # Validate that all target models are registered for this tenant
        registered_models = await self._tenant_repo.list_models(tenant_id)
        registered_names = {r["model_name"] for r in registered_models}
        for rule_def in preset.rules:
            concrete = model_mapping.resolve(rule_def.target_level)
            if concrete not in registered_names:
                raise ValueError(
                    f"Model '{concrete}' is not registered for this tenant"
                )

        # Check idempotency: reject if intents from this preset already exist
        existing_intents = await self._repo.list_intents(tenant_id)
        existing_names = {r["name"] for r in existing_intents}
        preset_intent_names = {i.name for i in preset.intents}
        overlap = existing_names & preset_intent_names
        if overlap:
            raise ValueError(
                f"Preset '{preset_name}' appears already applied: "
                f"intents {overlap} already exist"
            )

        intents_created = 0
        examples_created = 0
        rules_created = 0

        # Run all DB writes in a single transaction
        async with self._repo._pool.acquire() as conn:
            async with conn.transaction():
                # Create intents with examples
                for intent_def in preset.intents:
                    intent_row = await conn.fetchrow(
                        self._repo._sql.query("insert_intent"),
                        tenant_id, intent_def.name, intent_def.description, 0.7,
                    )
                    intents_created += 1

                    for example_text in intent_def.examples:
                        await conn.fetchrow(
                            self._repo._sql.query("insert_intent_example"),
                            intent_row["id"], example_text, None,
                        )
                        examples_created += 1

                # Create rules with concrete model names
                for priority, rule_def in enumerate(preset.rules):
                    concrete_model = model_mapping.resolve(rule_def.target_level)

                    rule_row = await conn.fetchrow(
                        self._repo._sql.query("insert_rule"),
                        tenant_id, rule_def.name, priority, rule_def.is_default,
                        concrete_model,
                    )
                    rules_created += 1

                    # Add conditions
                    if rule_def.conditions:
                        for c in rule_def.conditions:
                            await conn.fetchrow(
                                self._repo._sql.query("insert_condition"),
                                rule_row["id"], c.condition_type, c.operator,
                                c.field, json.dumps(c.value), False,
                            )

        logger.info(
            "preset_applied",
            tenant_id=str(tenant_id),
            preset=preset_name,
            rules=rules_created,
            intents=intents_created,
        )

        return PresetApplyResult(
            preset_name=preset_name,
            rules_created=rules_created,
            intents_created=intents_created,
            examples_created=examples_created,
        )
