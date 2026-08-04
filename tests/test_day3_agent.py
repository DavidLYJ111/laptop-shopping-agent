import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from shopping_agent.agent.bailian_provider import AIServiceError, BailianProvider
from shopping_agent.agent.schemas import (
    ExtractedConstraint,
    ExtractedPreference,
    IntentResult,
    IntentType,
    RecommendationDraft,
    RecommendRequest,
    ScenarioType,
)
from shopping_agent.agent.service import (
    AgentValidationError,
    DATA_DISCLAIMER,
    ShoppingAgentService,
)
from shopping_agent.api.main import app
from shopping_agent.api.routes import get_agent_service
from shopping_agent.config import Settings
from shopping_agent.data import load_documents, load_products
from shopping_agent.models import DocumentType
from shopping_agent.retrieval import EvidenceRetriever

ROOT = Path(__file__).resolve().parents[1]


def make_intent(*, constraints=None, preferences=None, scenario=ScenarioType.CODING_DATA):
    return IntentResult(
        intent=IntentType.PURCHASE,
        scenario=scenario,
        hard_constraints=constraints or [],
        soft_preferences=preferences or [],
        mentioned_products=[],
        missing_critical_info=[],
        need_followup=False,
        followup_questions=[],
        assumptions=[],
    )


class FakeProvider:
    def __init__(self, intent, *, bad_sku=False, bad_evidence=False, always_fail=False):
        self.intent = intent
        self.bad_sku = bad_sku
        self.bad_evidence = bad_evidence
        self.always_fail = always_fail
        self.calls = []

    def parse_structured(self, *, system_prompt, user_input, schema):
        self.calls.append(schema.__name__)
        if self.always_fail:
            raise AIServiceError("百炼千问 API 调用失败，请检查网络、模型权限或服务状态。")
        if schema is IntentResult:
            return self.intent
        context = json.loads(user_input.split("\n上次", maxsplit=1)[0])
        candidates = context["candidate_products_in_fixed_order"]
        evidence = context["allowed_evidence"]
        items = []
        for candidate in candidates:
            ids = [item["evidence_id"] for item in evidence if item["sku_id"] == candidate["sku_id"]][:2]
            items.append({
                "sku_id": "invented_sku" if self.bad_sku else candidate["sku_id"],
                "rank": candidate["rank"],
                "short_reason": "基于结构化参数和已检索证据的保守推荐。",
                "matched_needs": ["满足已声明条件"],
                "tradeoffs": ["当前为 mock 数据"],
                "evidence_ids": ["invented_evidence"] if self.bad_evidence else ids,
            })
        return RecommendationDraft.model_validate({
            "need_summary": "需要一台符合预算和使用场景的笔记本。",
            "overall_advice": "优先核对硬约束，再比较性能与便携取舍。",
            "recommendations": items,
            "comparison_summary": "候选在性能、重量和价格之间各有取舍。",
            "assumptions": [],
            "conflict_analysis": "约束组合过严，需要适当放宽。" if context["search_mode"] == "nearest" else None,
            "data_disclaimer": DATA_DISCLAIMER,
        })


@pytest.fixture()
def service_factory():
    products = load_products(ROOT / "data" / "products.jsonl")
    documents = load_documents(
        ROOT / "data" / "documents.jsonl",
        valid_sku_ids={product.sku_id for product in products},
    )

    def build(intent, **provider_options):
        provider = FakeProvider(intent, **provider_options)
        return ShoppingAgentService(products, EvidenceRetriever(documents), provider), provider

    return build


def constraint(field, value, *, priority="normal", relaxable=True):
    return ExtractedConstraint(
        field=field,
        value=value,
        source_type="explicit",
        source_text="测试输入",
        confidence=1.0,
        priority=priority,
        relaxable=relaxable,
    )


def test_structured_constraint_schema_rejects_relaxable_critical():
    with pytest.raises(ValidationError, match="critical constraints"):
        constraint("budget_max", 7000, priority="critical", relaxable=True)


def test_fuzzy_portability_stays_soft(service_factory):
    preference = ExtractedPreference(
        field="portability", level="high", values=[], source_text="希望轻便", confidence=.95
    )
    service, _ = service_factory(make_intent(preferences=[preference]))
    response = service.recommend(RecommendRequest(message="希望轻便一点，主要写代码"))
    assert response.hard_constraints == []
    assert response.soft_preferences[0].field == "portability"


def test_form_constraints_override_model_extraction(service_factory):
    service, _ = service_factory(make_intent(constraints=[constraint("budget_max", 9000)]))
    response = service.recommend(RecommendRequest.model_validate({
        "message": "预算九千左右，主要写代码",
        "form_constraints": {"budget_max": 6000, "scenario": "编程开发/数据分析"},
    }))
    budget = next(item for item in response.hard_constraints if item.field == "budget_max")
    assert budget.value == 6000
    assert budget.source_text == "前端表单"
    assert all(item.product.price <= 6000 for item in response.recommendations)


def test_normal_recommendation_chain(service_factory):
    intent = make_intent(constraints=[constraint("budget_max", 7000), constraint("ram_min", 16)])
    service, provider = service_factory(intent)
    response = service.recommend(RecommendRequest(message="预算7000以内，至少16GB，写代码"))
    assert response.search_mode.value == "normal"
    assert 1 <= len(response.recommendations) <= 3
    assert all(item.is_exact_match and not item.violations for item in response.recommendations)
    assert provider.calls == ["IntentResult", "RecommendationDraft"]


def test_nearest_conflict_chain(service_factory):
    intent = make_intent(
        constraints=[
            constraint("budget_max", 3000),
            constraint("gpu_required", True, priority="critical", relaxable=False),
            constraint("weight_max", 1.0),
        ],
        scenario=ScenarioType.GAMING,
    )
    service, _ = service_factory(intent)
    response = service.recommend(RecommendRequest(message="三千以内、必须独显、重量不超过1kg"))
    assert response.search_mode.value == "nearest"
    assert 1 <= len(response.recommendations) <= 2
    assert response.conflict_analysis is not None
    assert all(not item.is_exact_match and item.violations for item in response.recommendations)


def test_generated_sku_must_come_from_search(service_factory):
    service, provider = service_factory(make_intent(), bad_sku=True)
    with pytest.raises(AgentValidationError, match="未通过确定性校验"):
        service.recommend(RecommendRequest(message="推荐一台办公本"))
    assert provider.calls.count("RecommendationDraft") == 2


def test_generated_evidence_id_must_exist(service_factory):
    service, _ = service_factory(make_intent(), bad_evidence=True)
    with pytest.raises(AgentValidationError, match="未通过确定性校验"):
        service.recommend(RecommendRequest(message="推荐一台办公本"))


def test_derived_documents_are_excluded_from_retrieval():
    documents = load_documents(ROOT / "data" / "documents.jsonl")
    retriever = EvidenceRetriever(documents)
    evidence = retriever.retrieve(
        query="编程开发", scenario="编程开发/数据分析",
        sku_ids=["lenovo_thinkbook16_mock_32_1024"], per_sku=3,
    )
    assert evidence
    assert all(item.document_type in {"fact", "evidence"} for item in evidence)
    derived_ids = {d.document_id for d in documents if d.document_type == DocumentType.DERIVED}
    assert not ({item.evidence_id for item in evidence} & derived_ids)


def test_bailian_failure_is_readable_and_does_not_expose_key():
    secret = "test-api-key-not-a-real-secret"

    class FailingCompletions:
        def create(self, **kwargs):
            raise RuntimeError(f"upstream failure using {secret}")

    class Chat:
        completions = FailingCompletions()

    class Client:
        chat = Chat()

    provider = BailianProvider(Settings(bailian_api_key=secret), client=Client())
    with pytest.raises(AIServiceError) as exc:
        provider.parse_structured(system_prompt="system", user_input="user", schema=IntentResult)
    assert "百炼千问 API 调用失败" in str(exc.value)
    assert secret not in str(exc.value)


def test_bailian_provider_uses_json_mode_and_validates_schema():
    captured = {}

    class Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            content = make_intent().model_dump_json()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = BailianProvider(Settings(bailian_api_key="test-key"), client=client)
    result = provider.parse_structured(
        system_prompt="你是测试助手。",
        user_input="请解析购买需求。",
        schema=IntentResult,
    )

    assert result.intent == IntentType.PURCHASE
    assert captured["model"] == "qwen-plus"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["extra_body"] == {"enable_thinking": False}
    assert "JSON Schema" in captured["messages"][1]["content"]


def test_health_reports_ai_disabled_without_key(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "")
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "ai_enabled": False, "data_mode": "mock", "product_count": 10
    }


def test_missing_api_key_returns_clear_503(monkeypatch):
    monkeypatch.setenv("BAILIAN_API_KEY", "")
    get_agent_service.cache_clear()
    client = TestClient(app)
    response = client.post("/api/recommend", json={"message": "推荐一台编程笔记本"})
    assert response.status_code == 503
    assert "BAILIAN_API_KEY" in response.json()["detail"]


def test_api_recommend_with_mocked_service(service_factory):
    service, _ = service_factory(make_intent(constraints=[constraint("budget_max", 7000)]))
    app.dependency_overrides[get_agent_service] = lambda: service
    try:
        response = TestClient(app).post("/api/recommend", json={"message": "七千以内的办公本"})
        assert response.status_code == 200
        assert response.json()["recommendations"]
        assert response.json()["data_disclaimer"] == DATA_DISCLAIMER
    finally:
        app.dependency_overrides.clear()


def test_root_returns_day3_html():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "真实 AI 导购 Agent" in response.text
    assert 'fetch("/api/recommend"' in response.text
