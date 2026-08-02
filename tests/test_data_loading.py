import json
from pathlib import Path

import pytest

from shopping_agent.data import DataLoadError, load_documents, load_products
from shopping_agent.models import DocumentType


def test_load_seed_products(products):
    assert len(products) == 10
    assert len({product.sku_id for product in products}) == 10
    assert all(product.data_kind.value == "mock" for product in products)


def test_load_documents_and_trust_boundary(products):
    path = Path(__file__).resolve().parents[1] / "data" / "documents.jsonl"
    documents = load_documents(path, valid_sku_ids={product.sku_id for product in products})
    assert len(documents) == 30
    assert {document.document_type for document in documents} == set(DocumentType)
    assert all(document.is_trusted_evidence for document in documents if document.document_type != DocumentType.DERIVED)
    assert not any(document.is_trusted_evidence for document in documents if document.document_type == DocumentType.DERIVED)


def test_invalid_enum_fails_with_readable_location(tmp_path):
    source = Path(__file__).resolve().parents[1] / "data" / "products.jsonl"
    record = json.loads(source.read_text(encoding="utf-8").splitlines()[0])
    record["product_category"] = "台式机"
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DataLoadError, match=r"bad\.jsonl:1.*product_category"):
        load_products(path)


def test_missing_required_field_fails(tmp_path):
    path = tmp_path / "missing.jsonl"
    path.write_text('{"sku_id":"only_id"}', encoding="utf-8")
    with pytest.raises(DataLoadError, match="Field required"):
        load_products(path)


def test_duplicate_sku_fails(tmp_path):
    source = Path(__file__).resolve().parents[1] / "data" / "products.jsonl"
    line = source.read_text(encoding="utf-8").splitlines()[0]
    path = tmp_path / "duplicate.jsonl"
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(DataLoadError, match="sku_id 重复"):
        load_products(path)


def test_numeric_range_fails(tmp_path):
    source = Path(__file__).resolve().parents[1] / "data" / "products.jsonl"
    record = json.loads(source.read_text(encoding="utf-8").splitlines()[0])
    record["price"] = 1
    path = tmp_path / "range.jsonl"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DataLoadError, match="greater than or equal to 2000"):
        load_products(path)

