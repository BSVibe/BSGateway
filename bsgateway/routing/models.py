from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TierConfig:
    """Score range to model mapping for a routing tier."""

    name: str
    score_range: tuple[int, int]
    model: str


@dataclass
class NexusHeaderConfig:
    """Configurable header names for BSNexus metadata extraction."""

    prefix: str = "x-bsnexus"
    task_type_field: str = "task-type"
    priority_field: str = "priority"
    complexity_hint_field: str = "complexity-hint"

    @property
    def task_type(self) -> str:
        return f"{self.prefix}-{self.task_type_field}"

    @property
    def priority(self) -> str:
        return f"{self.prefix}-{self.priority_field}"

    @property
    def complexity_hint(self) -> str:
        return f"{self.prefix}-{self.complexity_hint_field}"


@dataclass
class NexusMetadata:
    """Optional task metadata extracted from X-BSNexus-* request headers."""

    task_type: str | None = None
    priority: str | None = None  # "low" | "medium" | "high" | "critical"
    complexity_hint: int | None = None  # 0-100


@dataclass
class RoutingDecision:
    """Record of how a request was routed."""

    method: str  # "passthrough" | "alias" | "auto"
    original_model: str
    resolved_model: str
    complexity_score: int | None = None
    tier: str | None = None
    nexus_metadata: NexusMetadata | None = None
    decision_source: str | None = None  # "classifier" | "blend" | "priority_override"


@dataclass
class ClassifierWeights:
    """Weights for each complexity signal."""

    token_count: float = 0.25
    system_prompt: float = 0.20
    keyword_patterns: float = 0.25
    conversation_length: float = 0.10
    code_complexity: float = 0.15
    tool_usage: float = 0.05


@dataclass
class ClassifierConfig:
    """Configuration for the complexity classifier."""

    weights: ClassifierWeights = field(default_factory=ClassifierWeights)
    token_thresholds: dict[str, int] = field(
        default_factory=lambda: {"low": 500, "medium": 2000, "high": 8000}
    )
    complex_keywords: list[str] = field(default_factory=list)
    simple_keywords: list[str] = field(default_factory=list)


@dataclass
class LLMClassifierConfig:
    """Configuration for the LLM-based classifier."""

    api_base: str = "http://host.docker.internal:11434"
    model: str = "llama3"
    timeout: float = 3.0


@dataclass
class EmbeddingConfig:
    """Configuration for embedding generation."""

    api_base: str = "http://host.docker.internal:11434"
    model: str = "nomic-embed-text"
    timeout: float = 5.0
    max_chars: int = 1000


@dataclass
class CollectorConfig:
    """Configuration for routing data collection."""

    enabled: bool = True
    embedding: EmbeddingConfig | None = field(default_factory=EmbeddingConfig)


@dataclass
class RegionConfig:
    """Configuration for multi-region model deployment."""

    region: str  # "us-east" | "us-west" | "eu-west" | etc.
    api_base: str | None = None  # Override api_base for this region
    latency_ms: int = 0  # Estimated latency in milliseconds
    priority: int = 0  # Lower number = higher priority


@dataclass
class CostOptimizationConfig:
    """Configuration for cost-optimized routing."""

    enabled: bool = True
    cost_per_1k_input: float = 0.0  # in USD
    cost_per_1k_output: float = 0.0  # in USD
    fallback_cost_multiplier: float = 1.5  # Cost threshold before falling back


@dataclass
class ABTestConfig:
    """A/B test variant configuration."""

    variant_id: str  # "control" | "variant-a" | "variant-b" | etc.
    model: str  # Target model for this variant
    traffic_percentage: float = 50.0  # 0-100
    metadata: dict = field(default_factory=dict)


@dataclass
class RoutingConfig:
    """Full routing configuration loaded from YAML."""

    tiers: list[TierConfig] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)
    auto_route_patterns: list[str] = field(default_factory=list)
    passthrough_models: set[str] = field(default_factory=set)
    # Phase 3 / TASK-004 — raw yaml ``model_list`` entries normalised to
    # ``{name, litellm_model, litellm_params}``. Feeds the per-tenant
    # ``ModelRegistryService`` so the registry's "system" half stays in
    # lock-step with whatever the operator put in ``gateway.yaml``.
    yaml_model_list: list[dict] = field(default_factory=list)
    classifier: ClassifierConfig = field(default_factory=ClassifierConfig)
    fallback_tier: str = "medium"
    classifier_strategy: str = "llm"
    llm_classifier: LLMClassifierConfig = field(default_factory=LLMClassifierConfig)
    collector: CollectorConfig = field(default_factory=CollectorConfig)
    nexus_headers: NexusHeaderConfig = field(default_factory=NexusHeaderConfig)
    # Multi-region and advanced routing
    regions: list[RegionConfig] = field(default_factory=list)
    cost_optimization: CostOptimizationConfig = field(default_factory=CostOptimizationConfig)
    ab_tests: dict[str, list[ABTestConfig]] = field(default_factory=dict)
