"""Two-call AI workflow around deterministic search and local evidence retrieval."""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable
from uuid import uuid4

from pydantic import ValidationError

from shopping_agent.agent.openai_provider import AIServiceError, OpenAIProvider
from shopping_agent.agent.prompts import load_prompt
from shopping_agent.agent.schemas import (
    ConflictAnalysis,
    EvidenceItem,
    ExtractedConstraint,
    ExtractedPreference,
    FormConstraints,
    GeneratedRecommendation,
    IntentResult,
    ProductView,
    RecommendRequest,
    RecommendResponse,
    RecommendationDraft,
    RecommendationItem,
    ScenarioType,
)
from shopping_agent.models import (
    ConstraintPriority,
    ConstraintSource,
    HardConstraints,
    Product,
    ProductSearchResult,
    SearchMode,
    SearchRequest,
    SoftPreferences,
)
from shopping_agent.retrieval import EvidenceRetriever
from shopping_agent.search import search_products

DATA_DISCLAIMER = "当前商品为演示数据，不代表实时市场信息"

SCENARIO_LABELS = {
    ScenarioType.OFFICE: "办公学习",
    ScenarioType.CODING_DATA: "编程开发/数据分析",
    ScenarioType.AI_TRAINING: "AI/深度学习",
    ScenarioType.GAMING: "游戏娱乐",
    ScenarioType.CREATIVE: "视频剪辑/设计创作",
    ScenarioType.GENERAL: "办公学习",
}
LABEL_TO_SCENARIO = {label: key for key, label in SCENARIO_LABELS.items()}


class AgentValidationError(RuntimeError):
    pass


@dataclass
class ShoppingAgentService:
    products: list[Product]
    retriever: EvidenceRetriever
    provider: OpenAIProvider

    def recommend(self, request: RecommendRequest) -> RecommendResponse:
        intent = self._extract_with_one_retry(request)
        merged_constraints, merged_preferences, scenario = self._merge_form(intent, request.form_constraints)
        intent = intent.model_copy(update={
            "hard_constraints": merged_constraints,
            "soft_preferences": merged_preferences,
            "scenario": scenario,
        })

        search_request = SearchRequest(
            hard_constraints=self._to_hard_constraints(merged_constraints),
            soft_preferences=self._to_soft_preferences(merged_preferences, scenario),
            search_mode=SearchMode.NORMAL,
            top_k=3,
        )
        search_response = search_products(self.products, search_request)
        candidates = search_response.results or search_response.nearest_candidates
        evidence = self.retriever.retrieve(
            query=request.message,
            scenario=SCENARIO_LABELS[scenario],
            sku_ids=[candidate.sku_id for candidate in candidates],
            per_sku=3,
        ) if candidates else []

        draft = self._generate_with_one_retry(
            request=request,
            intent=intent,
            candidates=candidates,
            evidence=evidence,
            search_mode=search_response.search_mode,
        )
        response = self._build_response(
            intent=intent,
            draft=draft,
            candidates=candidates,
            evidence=evidence,
            search_mode=search_response.search_mode,
            candidate_count=search_response.filtered_count,
        )
        self._validate_response(response, candidates, evidence)
        return response

    def _extract_with_one_retry(self, request: RecommendRequest) -> IntentResult:
        payload = json.dumps({
            "user_message": request.message,
            "form_constraints": request.form_constraints.model_dump(exclude_none=True),
            "session_id": request.session_id,
        }, ensure_ascii=False)
        error_note = ""
        for attempt in range(2):
            try:
                return self.provider.parse_structured(
                    system_prompt=load_prompt("constraint_extraction.txt"),
                    user_input=payload + error_note,
                    schema=IntentResult,
                )
            except (AIServiceError, ValidationError, ValueError) as exc:
                if attempt == 1:
                    raise
                error_note = "\n上次输出未通过结构校验。请严格按 Schema 修正一次，不要添加额外字段。"
        raise AgentValidationError("需求解析失败。")

    def _merge_form(
        self,
        intent: IntentResult,
        form: FormConstraints,
    ) -> tuple[list[ExtractedConstraint], list[ExtractedPreference], ScenarioType]:
        constraints: OrderedDict[str, ExtractedConstraint] = OrderedDict(
            (item.field, item) for item in intent.hard_constraints
        )
        form_values = {
            "budget_max": form.budget_max,
            "ram_min": form.ram_min,
            "gpu_required": form.gpu_required,
            "weight_max": form.weight_max,
        }
        for field, value in form_values.items():
            if value is None or (field == "ram_min" and value == 0):
                continue
            constraints[field] = ExtractedConstraint(
                field=field,
                value=value,
                source_type=ConstraintSource.EXPLICIT,
                source_text="前端表单",
                confidence=1.0,
                priority=ConstraintPriority.NORMAL,
                relaxable=True,
            )

        scenario = LABEL_TO_SCENARIO.get(form.scenario or "", intent.scenario)
        preferences = list(intent.soft_preferences)
        return list(constraints.values()), preferences, scenario

    @staticmethod
    def _to_hard_constraints(items: list[ExtractedConstraint]) -> HardConstraints:
        return HardConstraints.model_validate({
            item.field: {
                "value": item.value,
                "source_type": item.source_type,
                "source_text": item.source_text,
                "confidence": item.confidence,
                "priority": item.priority,
                "relaxable": item.relaxable,
            }
            for item in items
        })

    @staticmethod
    def _to_soft_preferences(
        items: list[ExtractedPreference], scenario: ScenarioType
    ) -> SoftPreferences:
        data: dict[str, object] = {"scenarios": [SCENARIO_LABELS[scenario]]}
        for item in items:
            if item.field in {"performance", "portability", "battery_life", "value_for_money"}:
                data[item.field] = item.level
            elif item.field == "brand":
                data["brand"] = item.values
            elif item.field == "scenarios" and item.values:
                data["scenarios"] = list(dict.fromkeys([SCENARIO_LABELS[scenario], *item.values]))
        return SoftPreferences.model_validate(data)

    def _generate_with_one_retry(
        self,
        *,
        request: RecommendRequest,
        intent: IntentResult,
        candidates: list[ProductSearchResult],
        evidence: list[EvidenceItem],
        search_mode: SearchMode,
    ) -> RecommendationDraft:
        context = {
            "user_message": request.message,
            "intent_result": intent.model_dump(mode="json"),
            "search_mode": search_mode.value,
            "candidate_products_in_fixed_order": [
                {
                    "sku_id": item.sku_id,
                    "rank": item.rank,
                    "product": item.product.model_dump(mode="json"),
                    "satisfied_constraints": item.satisfied_constraints,
                    "violations": [violation.model_dump(mode="json") for violation in item.violations],
                    "dimension_scores": item.dimension_scores,
                }
                for item in candidates
            ],
            "allowed_evidence": [item.model_dump(mode="json") for item in evidence],
            "data_disclaimer": DATA_DISCLAIMER,
        }
        correction = ""
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                draft = self.provider.parse_structured(
                    system_prompt=load_prompt("recommendation_system.txt"),
                    user_input=json.dumps(context, ensure_ascii=False) + correction,
                    schema=RecommendationDraft,
                )
                self._validate_draft(draft, candidates, evidence)
                return draft
            except (AIServiceError, ValidationError, AgentValidationError, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    correction = (
                        "\n上次结果未通过确定性校验。请仅使用候选 SKU、固定 rank 和允许的 evidence_id 修正一次。"
                    )
        raise AgentValidationError("推荐内容生成后仍未通过确定性校验。") from last_error

    @staticmethod
    def _validate_draft(
        draft: RecommendationDraft,
        candidates: list[ProductSearchResult],
        evidence: list[EvidenceItem],
    ) -> None:
        expected = [(candidate.sku_id, candidate.rank) for candidate in candidates]
        actual = [(item.sku_id, item.rank) for item in draft.recommendations]
        if actual != expected:
            raise AgentValidationError("模型不得修改候选商品或确定性排名。")
        evidence_ids = {item.evidence_id for item in evidence}
        if any(evidence_id not in evidence_ids for item in draft.recommendations for evidence_id in item.evidence_ids):
            raise AgentValidationError("模型引用了不存在的 evidence_id。")
        if DATA_DISCLAIMER not in draft.data_disclaimer:
            raise AgentValidationError("缺少 mock 数据声明。")

    def _build_response(
        self,
        *,
        intent: IntentResult,
        draft: RecommendationDraft,
        candidates: list[ProductSearchResult],
        evidence: list[EvidenceItem],
        search_mode: SearchMode,
        candidate_count: int,
    ) -> RecommendResponse:
        generated_by_sku: dict[str, GeneratedRecommendation] = {
            item.sku_id: item for item in draft.recommendations
        }
        recommendations = []
        for candidate in candidates:
            generated = generated_by_sku[candidate.sku_id]
            recommendations.append(RecommendationItem(
                sku_id=candidate.sku_id,
                rank=candidate.rank,
                is_exact_match=search_mode == SearchMode.NORMAL,
                match_score=candidate.total_score,
                product=ProductView.model_validate(
                    candidate.product.model_dump(include=set(ProductView.model_fields))
                ),
                short_reason=generated.short_reason,
                matched_needs=generated.matched_needs,
                tradeoffs=generated.tradeoffs,
                evidence_ids=generated.evidence_ids,
                satisfied_constraints=candidate.satisfied_constraints,
                violations=candidate.violations,
                violation_count=len(candidate.violations),
                violation_cost=candidate.violation_cost,
                dimension_scores=candidate.dimension_scores,
            ))

        conflict = None
        if search_mode == SearchMode.NEAREST:
            violated_fields = sorted({
                violation.field for candidate in candidates for violation in candidate.violations
            })
            suggestions = [f"考虑放宽约束：{field}" for field in violated_fields[:3]]
            conflict = ConflictAnalysis(
                summary=draft.conflict_analysis or "当前没有完全满足全部硬约束的商品。",
                suggestions=suggestions,
                violated_fields=violated_fields,
            )

        return RecommendResponse(
            request_id=str(uuid4()),
            intent=intent.intent,
            need_summary=draft.need_summary,
            overall_advice=draft.overall_advice,
            hard_constraints=intent.hard_constraints,
            soft_preferences=intent.soft_preferences,
            scenario=intent.scenario,
            need_followup=intent.need_followup,
            followup_questions=intent.followup_questions,
            search_mode=search_mode,
            candidate_count=candidate_count,
            recommendations=recommendations,
            comparison_summary=draft.comparison_summary,
            conflict_analysis=conflict,
            assumptions=list(dict.fromkeys([*intent.assumptions, *draft.assumptions])),
            evidence=evidence,
            data_disclaimer=DATA_DISCLAIMER,
        )

    @staticmethod
    def _validate_response(
        response: RecommendResponse,
        candidates: list[ProductSearchResult],
        evidence: list[EvidenceItem],
    ) -> None:
        allowed_skus = {candidate.sku_id for candidate in candidates}
        if any(item.sku_id not in allowed_skus for item in response.recommendations):
            raise AgentValidationError("响应包含搜索结果之外的 SKU。")
        if response.search_mode == SearchMode.NORMAL and any(item.violations for item in response.recommendations):
            raise AgentValidationError("normal 推荐包含违反硬约束的商品。")
        evidence_ids = {item.evidence_id for item in evidence}
        if any(eid not in evidence_ids for item in response.recommendations for eid in item.evidence_ids):
            raise AgentValidationError("响应引用了不存在的证据。")
        if response.search_mode == SearchMode.NEAREST and any(
            item.is_exact_match or not item.violations for item in response.recommendations
        ):
            raise AgentValidationError("nearest 候选必须明确携带违反项。")
        if DATA_DISCLAIMER not in response.data_disclaimer:
            raise AgentValidationError("响应缺少 mock 数据声明。")
