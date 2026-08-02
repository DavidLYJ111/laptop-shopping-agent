"""Readable JSONL loading and dataset-level validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from shopping_agent.models import Document, Product

ModelT = TypeVar("ModelT", bound=BaseModel)


class DataLoadError(ValueError):
    """Raised when a dataset cannot be read or validated."""


def _load_jsonl(path: str | Path, model: type[ModelT]) -> list[ModelT]:
    file_path = Path(path)
    if not file_path.is_file():
        raise DataLoadError(f"数据文件不存在: {file_path}")

    records: list[ModelT] = []
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DataLoadError(f"无法读取数据文件 {file_path}: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DataLoadError(
                f"{file_path}:{line_number} JSON 格式错误: {exc.msg}（第 {exc.colno} 列）"
            ) from exc
        try:
            records.append(model.model_validate(raw))
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            raise DataLoadError(f"{file_path}:{line_number} 数据校验失败: {details}") from exc
    return records


def load_products(path: str | Path) -> list[Product]:
    products = _load_jsonl(path, Product)
    seen: dict[str, int] = {}
    for index, product in enumerate(products, start=1):
        if product.sku_id in seen:
            raise DataLoadError(
                f"{path}: sku_id 重复: {product.sku_id!r}（记录 {seen[product.sku_id]} 与 {index}）"
            )
        seen[product.sku_id] = index
    return products


def load_documents(
    path: str | Path, *, valid_sku_ids: set[str] | None = None
) -> list[Document]:
    documents = _load_jsonl(path, Document)
    seen: dict[str, int] = {}
    for index, document in enumerate(documents, start=1):
        if document.document_id in seen:
            raise DataLoadError(
                f"{path}: document_id 重复: {document.document_id!r}"
            )
        seen[document.document_id] = index
        if valid_sku_ids is not None and document.sku_id not in valid_sku_ids:
            raise DataLoadError(
                f"{path}: 文档 {document.document_id!r} 引用了不存在的 sku_id {document.sku_id!r}"
            )
    return documents

