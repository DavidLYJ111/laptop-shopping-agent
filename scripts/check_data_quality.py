"""Validate JSONL records and print a compact quality report."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from shopping_agent.data import DataLoadError, load_documents, load_products


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        products = load_products(root / "data" / "products.jsonl")
        documents = load_documents(
            root / "data" / "documents.jsonl",
            valid_sku_ids={product.sku_id for product in products},
        )
    except DataLoadError as exc:
        print(f"数据质量检查失败：{exc}")
        return 1

    categories = Counter(product.product_category.value for product in products)
    document_types = Counter(document.document_type.value for document in documents)
    trusted_count = sum(document.is_trusted_evidence for document in documents)
    mock_count = sum(product.data_kind.value in {"mock", "demo"} for product in products)
    print(f"商品：{len(products)} 条，SKU 唯一性与字段校验通过")
    print(f"品类覆盖：{dict(categories)}")
    print(f"文档：{len(documents)} 条，类型分布：{dict(document_types)}")
    print(f"可信证据候选（fact/evidence）：{trusted_count} 条；derived 已排除")
    print(f"演示/模拟商品：{mock_count} 条（不可当作真实已核验市场数据）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

