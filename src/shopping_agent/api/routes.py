"""HTTP routes and dependency construction."""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from shopping_agent.agent.openai_provider import (
    AIConfigurationError,
    AIServiceError,
    OpenAIProvider,
)
from shopping_agent.agent.schemas import (
    HealthResponse,
    RecommendRequest,
    RecommendResponse,
)
from shopping_agent.agent.service import AgentValidationError, ShoppingAgentService
from shopping_agent.config import DATA_DIR, get_settings
from shopping_agent.data import DataLoadError, load_documents, load_products
from shopping_agent.retrieval import EvidenceRetriever

router = APIRouter(prefix="/api")


@lru_cache(maxsize=1)
def get_agent_service() -> ShoppingAgentService:
    settings = get_settings()
    products = load_products(DATA_DIR / "products.jsonl")
    documents = load_documents(
        DATA_DIR / "documents.jsonl",
        valid_sku_ids={product.sku_id for product in products},
    )
    try:
        provider = OpenAIProvider(settings)
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    return ShoppingAgentService(
        products=products,
        retriever=EvidenceRetriever(documents),
        provider=provider,
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    products = load_products(DATA_DIR / "products.jsonl")
    return HealthResponse(
        ai_enabled=get_settings().ai_enabled,
        product_count=len(products),
    )


@router.post("/recommend", response_model=RecommendResponse)
def recommend(
    request: RecommendRequest,
    service: ShoppingAgentService = Depends(get_agent_service),
) -> RecommendResponse:
    try:
        return service.recommend(request)
    except AIConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except AIServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except AgentValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except DataLoadError:
        raise HTTPException(status_code=500, detail="商品数据加载失败，请联系管理员。") from None
