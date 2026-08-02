"""Small deterministic retriever for the minimum RAG chain."""

from __future__ import annotations

import re
from collections import defaultdict

from shopping_agent.agent.schemas import EvidenceItem
from shopping_agent.models import Document, DocumentType

DOMAIN_KEYWORDS = (
    "办公", "学习", "编程", "开发", "数据分析", "AI", "深度学习", "游戏",
    "剪辑", "设计", "创作", "便携", "续航", "内存", "显卡", "屏幕", "重量",
)


def _query_terms(text: str) -> set[str]:
    terms = {token.casefold() for token in re.findall(r"[A-Za-z0-9]+", text)}
    terms.update(keyword.casefold() for keyword in DOMAIN_KEYWORDS if keyword.casefold() in text.casefold())
    return terms


class EvidenceRetriever:
    """Rank fact/evidence documents inside an already selected SKU set."""

    def __init__(self, documents: list[Document]) -> None:
        self._documents = [
            document
            for document in documents
            if document.document_type in {DocumentType.FACT, DocumentType.EVIDENCE}
        ]

    @property
    def evidence_ids(self) -> set[str]:
        return {document.document_id for document in self._documents}

    def retrieve(
        self,
        *,
        query: str,
        scenario: str,
        sku_ids: list[str],
        per_sku: int = 3,
    ) -> list[EvidenceItem]:
        if not 2 <= per_sku <= 4:
            raise ValueError("per_sku must be between 2 and 4")
        allowed = set(sku_ids)
        terms = _query_terms(f"{query} {scenario}")
        grouped: dict[str, list[tuple[float, Document]]] = defaultdict(list)

        for document in self._documents:
            if document.sku_id not in allowed:
                continue
            haystack = f"{document.source} {document.content}".casefold()
            overlap = sum(term in haystack for term in terms)
            # Facts remain available even for short or sparse queries.
            type_bonus = 0.25 if document.document_type == DocumentType.FACT else 0.15
            grouped[document.sku_id].append((overlap + type_bonus, document))

        results: list[EvidenceItem] = []
        for sku_id in sku_ids:
            ranked = sorted(
                grouped.get(sku_id, []),
                key=lambda item: (-item[0], item[1].document_id),
            )[:per_sku]
            results.extend(
                EvidenceItem(
                    evidence_id=document.document_id,
                    sku_id=document.sku_id,
                    document_type=document.document_type.value,
                    source=document.source,
                    content=document.content,
                )
                for _, document in ranked
            )
        return results

