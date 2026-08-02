"""Run a deliberately separate, billable smoke test against the real OpenAI API."""

from __future__ import annotations

import sys

from shopping_agent.agent.openai_provider import AIConfigurationError, OpenAIProvider
from shopping_agent.agent.schemas import FormConstraints, RecommendRequest
from shopping_agent.agent.service import ShoppingAgentService
from shopping_agent.config import DATA_DIR, get_settings
from shopping_agent.data import load_documents, load_products
from shopping_agent.retrieval import EvidenceRetriever


def main() -> int:
    settings = get_settings()
    if not settings.ai_enabled:
        print("未执行真实 OpenAI 冒烟测试：请先在 .env 设置 OPENAI_API_KEY。")
        return 2

    products = load_products(DATA_DIR / "products.jsonl")
    documents = load_documents(
        DATA_DIR / "documents.jsonl",
        valid_sku_ids={product.sku_id for product in products},
    )
    try:
        service = ShoppingAgentService(
            products=products,
            retriever=EvidenceRetriever(documents),
            provider=OpenAIProvider(settings),
        )
        response = service.recommend(RecommendRequest(
            message="预算 7000 元，用于编程和数据分析，希望便携，内存至少 32GB。",
            session_id="real-openai-smoke",
            form_constraints=FormConstraints(
                budget_max=7000,
                ram_min=32,
                scenario="编程开发/数据分析",
            ),
        ))
    except AIConfigurationError as exc:
        print(f"配置错误：{exc}")
        return 2
    except Exception as exc:  # Safe CLI boundary: never print provider internals.
        print(f"真实 OpenAI 冒烟测试失败：{type(exc).__name__}")
        return 1

    print(f"真实 OpenAI 冒烟测试通过：mode={response.search_mode.value}")
    print("候选 SKU：" + ", ".join(item.sku_id for item in response.recommendations))
    return 0


if __name__ == "__main__":
    sys.exit(main())
