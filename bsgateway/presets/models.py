from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field


@dataclass
class PresetIntent:
    """An intent definition within a preset template."""

    name: str
    description: str = ""
    examples: list[str] = field(default_factory=list)


@dataclass
class PresetCondition:
    """A condition within a preset rule."""

    condition_type: str
    field: str
    operator: str
    value: object


@dataclass
class PresetRule:
    """A routing rule within a preset template."""

    name: str
    target_level: str  # "economy", "balanced", "premium"
    is_default: bool = False
    conditions: list[PresetCondition] = field(default_factory=list)


@dataclass
class PresetTemplate:
    """A complete preset template with intents and rules."""

    name: str
    description: str
    intents: list[PresetIntent] = field(default_factory=list)
    rules: list[PresetRule] = field(default_factory=list)


class ModelMapping(BaseModel):
    """Maps abstract model levels to concrete model names."""

    economy: str = Field(..., min_length=1)
    balanced: str = Field(..., min_length=1)
    premium: str = Field(..., min_length=1)

    def resolve(self, level: str) -> str:
        mapping = {
            "economy": self.economy,
            "balanced": self.balanced,
            "premium": self.premium,
        }
        return mapping.get(level, self.balanced)


class PresetApplyRequest(BaseModel):
    """Request to apply a preset to a tenant."""

    preset_name: str = Field(..., min_length=1)
    model_mapping: ModelMapping


@dataclass
class PresetApplyResult:
    """Result of applying a preset."""

    preset_name: str
    rules_created: int
    intents_created: int
    examples_created: int
