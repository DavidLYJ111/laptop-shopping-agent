"""Structured Outputs and public API schemas for the Day 3 workflow."""

from __future__ import annotations

from enum import Enum
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shopping_agent.models import (
    ConstraintPriority,
    ConstraintSource,
    ConstraintViolation,
    PreferenceLevel,
    SearchMode,
)


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IntentType(str, Enum):
    PURCHASE = "purchase"
    COMPARE = "compare"
    INQUIRY = "inquiry"
    MULTIMODAL = "multimodal"


class ScenarioType(str, Enum):
    OFFICE = "office"
    CODING_DATA = "coding_data"
    AI_TRAINING = "ai_training"
    GAMING = "gaming"
    CREATIVE = "creative"
    GENERAL = "general"


HardField = Literal[
    "budget_max", "budget_min", "gpu_required", "gpu_vram_min", "ram_min",
    "storage_min", "weight_max", "screen_size_range", "resolution_min",
    "refresh_rate_min", "cpu_brand", "category", "required_ports", "brand",
]
SoftField = Literal[
    "performance", "portability", "battery_life", "value_for_money", "brand", "scenarios"
]
ConstraintValue: TypeAlias = int | float | bool | str | list[str] | list[float]


class ExtractedConstraint(AgentModel):
    field: HardField
    value: ConstraintValue
    source_type: ConstraintSource
    source_text: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    priority: ConstraintPriority
    relaxable: bool

    @model_validator(mode="after")
    def validate_critical(self) -> "ExtractedConstraint":
        if self.priority == ConstraintPriority.CRITICAL and self.relaxable:
            raise ValueError("critical constraints must not be relaxable")
        return self


class ExtractedPreference(AgentModel):
    field: SoftField
    level: PreferenceLevel
    values: list[str] = Field(default_factory=list)
    source_text: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class IntentResult(AgentModel):
    intent: IntentType
    scenario: ScenarioType
    hard_constraints: list[ExtractedConstraint]
    soft_preferences: list[ExtractedPreference]
    mentioned_products: list[str]
    missing_critical_info: list[str]
    need_followup: bool
    followup_questions: list[str]
    assumptions: list[str]

    @model_validator(mode="after")
    def validate_followup(self) -> "IntentResult":
        if self.need_followup and not self.followup_questions:
            raise ValueError("need_followup=true requires at least one question")
        if len(self.followup_questions) > 2:
            raise ValueError("at most two follow-up questions are allowed")
        return self


class GeneratedRecommendation(AgentModel):
    sku_id: str
    rank: int = Field(ge=1)
    short_reason: str = Field(min_length=1)
    matched_needs: list[str]
    tradeoffs: list[str]
    evidence_ids: list[str]


class RecommendationDraft(AgentModel):
    need_summary: str = Field(min_length=1)
    overall_advice: str = Field(min_length=1)
    recommendations: list[GeneratedRecommendation]
    comparison_summary: str
    assumptions: list[str]
    conflict_analysis: str | None
    data_disclaimer: str = Field(min_length=1)


class FormConstraints(AgentModel):
    budget_max: int | None = Field(default=None, ge=0, le=30000)
    ram_min: int | None = Field(default=None, ge=0, le=128)
    gpu_required: bool | None = None
    scenario: str | None = None
    weight_max: float | None = Field(default=None, ge=0.8, le=4.0)


class RecommendRequest(AgentModel):
    message: str = Field(min_length=2, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)
    form_constraints: FormConstraints = Field(default_factory=FormConstraints)


class EvidenceItem(AgentModel):
    evidence_id: str
    sku_id: str
    document_type: Literal["fact", "evidence"]
    source: str
    content: str


class ProductView(AgentModel):
    sku_id: str
    brand: str
    model_name: str
    product_category: str
    price: int
    cpu_model: str
    gpu_type: str
    gpu_model: str | None
    gpu_vram_gb: int | None
    ram_gb: int
    storage_capacity: int
    screen_size: float
    resolution: str
    refresh_rate: int | None
    weight_kg: float


class RecommendationItem(AgentModel):
    sku_id: str
    rank: int
    is_exact_match: bool
    match_score: float = Field(ge=0.0, le=1.0)
    product: ProductView
    short_reason: str
    matched_needs: list[str]
    tradeoffs: list[str]
    evidence_ids: list[str]
    satisfied_constraints: list[str]
    violations: list[ConstraintViolation]
    violation_count: int = Field(ge=0)
    violation_cost: float = Field(ge=0.0)
    dimension_scores: dict[str, float]


class ConflictAnalysis(AgentModel):
    summary: str
    suggestions: list[str]
    violated_fields: list[str]


class RecommendResponse(AgentModel):
    request_id: str
    intent: IntentType
    need_summary: str
    overall_advice: str
    hard_constraints: list[ExtractedConstraint]
    soft_preferences: list[ExtractedPreference]
    scenario: ScenarioType
    need_followup: bool
    followup_questions: list[str]
    search_mode: SearchMode
    candidate_count: int = Field(ge=0)
    recommendations: list[RecommendationItem]
    comparison_summary: str
    conflict_analysis: ConflictAnalysis | None
    assumptions: list[str]
    evidence: list[EvidenceItem]
    data_disclaimer: str


class HealthResponse(AgentModel):
    status: Literal["ok"] = "ok"
    ai_enabled: bool
    data_mode: Literal["mock"] = "mock"
    product_count: int

