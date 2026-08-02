"""Validated domain models shared by loading and deterministic search."""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Reject unknown fields so malformed datasets fail loudly."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductCategory(str, Enum):
    ULTRABOOK = "轻薄本"
    ALL_ROUNDER = "全能本"
    GAMING = "游戏本"


class GPUType(str, Enum):
    INTEGRATED = "核显"
    DISCRETE = "独立显卡"


class VerificationStatus(str, Enum):
    VERIFIED = "已核验"
    PARTIAL = "部分核验"
    PENDING = "待核验"


class DataKind(str, Enum):
    REAL = "real"
    DEMO = "demo"
    MOCK = "mock"


class DocumentType(str, Enum):
    FACT = "fact"
    EVIDENCE = "evidence"
    DERIVED = "derived"


class ConstraintSource(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    USER_ADJUSTED = "user_adjusted"


class ConstraintPriority(str, Enum):
    NORMAL = "normal"
    CRITICAL = "critical"
    RELAXABLE = "relaxable"


class SearchMode(str, Enum):
    NORMAL = "normal"
    NEAREST = "nearest"


class PreferenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Product(StrictModel):
    sku_id: str = Field(min_length=3, pattern=r"^[a-z0-9][a-z0-9_\-]+$")
    brand: str = Field(min_length=1)
    series: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    product_category: ProductCategory
    release_year: int = Field(ge=2020, le=2030)

    price: int = Field(ge=2000, le=30000)
    cpu_brand: str = Field(min_length=1)
    cpu_model: str = Field(min_length=1)
    cpu_cores: int | None = Field(default=None, ge=2, le=64)
    gpu_type: GPUType
    gpu_model: str | None = None
    gpu_vram_gb: int | None = Field(default=None, ge=0, le=32)
    gpu_tgp_w: int | None = Field(default=None, ge=0, le=250)
    ram_gb: Literal[8, 16, 32, 64, 128]
    storage_type: Literal["SSD"] = "SSD"
    storage_capacity: int = Field(ge=256, le=8192)
    screen_size: float = Field(ge=10.0, le=18.5)
    resolution: str = Field(pattern=r"^\d{3,5}x\d{3,5}$")
    refresh_rate: int | None = Field(default=None, ge=30, le=500)
    weight_kg: float = Field(ge=0.8, le=4.0)
    battery_wh: int | None = Field(default=None, ge=20, le=150)
    os: str | None = None
    ports: list[str] = Field(default_factory=list)

    product_title: str = Field(min_length=1)
    selling_points: list[str] = Field(default_factory=list)
    scenario_desc: str = ""
    pros_summary: str = ""
    cons_summary: str = ""
    user_review_summary: str = ""
    image_main: str | None = None
    image_param_page: str | None = None
    image_detail: str | None = None

    data_sources: list[str] = Field(min_length=1)
    verification_status: VerificationStatus
    collect_date: date
    data_kind: DataKind
    source_url: str | None = None
    tags: list[str] = Field(default_factory=list)

    cpu_performance_score: float = Field(ge=0.0, le=1.0)
    gpu_performance_score: float = Field(ge=0.0, le=1.0)
    portability_score: float = Field(ge=0.0, le=1.0)
    battery_capacity_score: float = Field(ge=0.0, le=1.0)

    @field_validator("data_sources", "ports")
    @classmethod
    def no_empty_list_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("list entries must not be blank")
        return value

    @model_validator(mode="after")
    def validate_gpu_fields(self) -> "Product":
        if self.gpu_type == GPUType.DISCRETE and not self.gpu_model:
            raise ValueError("discrete GPU products require gpu_model")
        if self.gpu_type == GPUType.INTEGRATED and (self.gpu_vram_gb or 0) > 0:
            raise ValueError("integrated GPU must not declare dedicated VRAM")
        return self

    @property
    def resolution_tuple(self) -> tuple[int, int]:
        width, height = self.resolution.lower().split("x", maxsplit=1)
        return int(width), int(height)


class Document(StrictModel):
    document_id: str = Field(min_length=3, pattern=r"^[a-z0-9][a-z0-9_\-]+$")
    sku_id: str = Field(min_length=3)
    document_type: DocumentType
    source: str = Field(min_length=1)
    source_date: date
    content: str = Field(min_length=3)
    data_kind: DataKind

    @property
    def is_trusted_evidence(self) -> bool:
        """Only fact/evidence may support later factual verification."""
        return self.document_type in {DocumentType.FACT, DocumentType.EVIDENCE}


CONSTRAINT_FIELDS = {
    "budget_max", "budget_min", "gpu_required", "gpu_vram_min", "ram_min",
    "storage_min", "weight_max", "screen_size_range", "resolution_min",
    "refresh_rate_min", "cpu_brand", "category", "required_ports", "brand",
}


class ConstraintItem(StrictModel):
    field: str
    value: Any
    source_type: ConstraintSource = ConstraintSource.EXPLICIT
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_text: str | None = None
    priority: ConstraintPriority = ConstraintPriority.NORMAL
    relaxable: bool = True

    @field_validator("field")
    @classmethod
    def known_field(cls, value: str) -> str:
        if value not in CONSTRAINT_FIELDS:
            raise ValueError(f"unsupported constraint field: {value}")
        return value

    @model_validator(mode="after")
    def critical_is_not_relaxable_by_default(self) -> "ConstraintItem":
        if self.priority == ConstraintPriority.CRITICAL and self.relaxable:
            raise ValueError("critical constraints must set relaxable=false")
        return self


class HardConstraints(StrictModel):
    budget_max: ConstraintItem | None = None
    budget_min: ConstraintItem | None = None
    gpu_required: ConstraintItem | None = None
    gpu_vram_min: ConstraintItem | None = None
    ram_min: ConstraintItem | None = None
    storage_min: ConstraintItem | None = None
    weight_max: ConstraintItem | None = None
    screen_size_range: ConstraintItem | None = None
    resolution_min: ConstraintItem | None = None
    refresh_rate_min: ConstraintItem | None = None
    cpu_brand: ConstraintItem | None = None
    category: ConstraintItem | None = None
    required_ports: ConstraintItem | None = None
    brand: ConstraintItem | None = None

    @model_validator(mode="before")
    @classmethod
    def wrap_plain_values(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        wrapped: dict[str, Any] = {}
        for field_name, raw in data.items():
            if raw is None:
                wrapped[field_name] = None
            elif isinstance(raw, ConstraintItem):
                wrapped[field_name] = raw
            elif isinstance(raw, dict) and "value" in raw:
                wrapped[field_name] = {"field": field_name, **raw}
            else:
                wrapped[field_name] = {"field": field_name, "value": raw}
        return wrapped

    @model_validator(mode="after")
    def validate_values(self) -> "HardConstraints":
        numeric_positive = {
            "budget_max", "budget_min", "gpu_vram_min", "ram_min", "storage_min",
            "weight_max", "refresh_rate_min",
        }
        for name, item in self.active_items():
            value = item.value
            if name in numeric_positive and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
                raise ValueError(f"{name} must be a non-negative number")
            if name == "gpu_required" and not isinstance(value, bool):
                raise ValueError("gpu_required must be boolean")
            if name == "screen_size_range":
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise ValueError("screen_size_range must contain [min, max]")
                if not all(isinstance(v, (int, float)) for v in value) or value[0] > value[1]:
                    raise ValueError("screen_size_range must be ordered numeric bounds")
            if name in {"required_ports", "brand"} and (not isinstance(value, list) or not value):
                raise ValueError(f"{name} must be a non-empty list")
            if name == "category" and value not in {e.value for e in ProductCategory}:
                raise ValueError("category has an unsupported value")
            if name == "resolution_min" and (not isinstance(value, str) or not re.fullmatch(r"\d{3,5}x\d{3,5}", value)):
                raise ValueError("resolution_min must use WIDTHxHEIGHT")
        if self.budget_min and self.budget_max and self.budget_min.value > self.budget_max.value:
            raise ValueError("budget_min cannot exceed budget_max")
        return self

    def active_items(self) -> list[tuple[str, ConstraintItem]]:
        return [
            (name, item)
            for name in self.__class__.model_fields
            if (item := getattr(self, name)) is not None
        ]


class SoftPreferences(StrictModel):
    performance: PreferenceLevel | None = None
    portability: PreferenceLevel | None = None
    battery_life: PreferenceLevel | None = None
    value_for_money: PreferenceLevel | None = None
    brand: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)


class SearchRequest(StrictModel):
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    soft_preferences: SoftPreferences = Field(default_factory=SoftPreferences)
    search_mode: SearchMode = SearchMode.NORMAL
    top_k: int = Field(default=5, ge=1, le=20)
    diversity_rerank: bool = True


class ConstraintViolation(StrictModel):
    field: str
    constraint_value: Any
    actual_value: Any
    magnitude: float = Field(ge=0.0, le=2.0)
    weighted_cost: float = Field(ge=0.0)
    priority: ConstraintPriority
    relaxable: bool
    is_critical: bool
    message: str


class ProductSearchResult(StrictModel):
    sku_id: str
    product: Product
    rank: int = Field(ge=1)
    total_score: float = Field(ge=0.0, le=1.0)
    dimension_scores: dict[str, float]
    constraint_check: dict[str, Literal["pass", "fail"]]
    violations: list[ConstraintViolation] = Field(default_factory=list)
    satisfied_constraints: list[str] = Field(default_factory=list)
    violation_cost: float = Field(default=0.0, ge=0.0)


class SearchResponse(StrictModel):
    results: list[ProductSearchResult] = Field(default_factory=list)
    nearest_candidates: list[ProductSearchResult] = Field(default_factory=list)
    filtered_count: int = Field(ge=0)
    total_pool: int = Field(ge=0)
    search_mode: SearchMode
