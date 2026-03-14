from __future__ import annotations

from uuid import UUID

import structlog

from bsgateway.presets.models import ModelMapping, PresetApplyResult
from bsgateway.presets.registry import PresetRegistry

logger = structlog.get_logger(__name__)

_registry = PresetRegistry()


class PresetService:
    """Apply preset templates to tenants."""

    def __init__(self, rules_repo: object) -> None:
        self._repo = rules_repo

    async def apply_preset(
        self,
        tenant_id: UUID,
        preset_name: str,
        model_mapping: ModelMapping,
    ) -> PresetApplyResult:
        """Apply a preset template to a tenant.

        Creates intents, examples, and rules based on the preset,
        mapping abstract model levels to concrete model names.
        """
        preset = _registry.get(preset_name)
        if not preset:
            raise ValueError(f"Unknown preset: {preset_name}")

        intents_created = 0
        examples_created = 0
        rules_created = 0

        # Create intents with examples
        for intent_def in preset.intents:
            intent_row = await self._repo.create_intent(
                tenant_id=tenant_id,
                name=intent_def.name,
                description=intent_def.description,
            )
            intents_created += 1

            for example_text in intent_def.examples:
                await self._repo.add_example(
                    intent_id=intent_row["id"],
                    text=example_text,
                )
                examples_created += 1

        # Create rules with concrete model names
        for priority, rule_def in enumerate(preset.rules):
            concrete_model = model_mapping.resolve(rule_def.target_level)

            rule_row = await self._repo.create_rule(
                tenant_id=tenant_id,
                name=rule_def.name,
                priority=priority,
                target_model=concrete_model,
                is_default=rule_def.is_default,
            )
            rules_created += 1

            # Add conditions
            if rule_def.conditions:
                conditions = [
                    {
                        "condition_type": c.condition_type,
                        "field": c.field,
                        "operator": c.operator,
                        "value": c.value,
                    }
                    for c in rule_def.conditions
                ]
                await self._repo.replace_conditions(
                    rule_row["id"], conditions,
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
