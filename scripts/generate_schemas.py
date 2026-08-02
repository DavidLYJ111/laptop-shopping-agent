"""Export JSON Schema from the authoritative Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path

from shopping_agent.models import Document, Product


def main() -> None:
    output_dir = Path(__file__).resolve().parents[1] / "data" / "schemas"
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, model in (
        ("product_schema.json", Product),
        ("document_schema.json", Document),
    ):
        target = output_dir / filename
        target.write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"已生成 {target}")


if __name__ == "__main__":
    main()

