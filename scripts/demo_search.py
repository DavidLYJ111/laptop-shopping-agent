"""Run three deterministic search examples."""

from __future__ import annotations

from pathlib import Path

from shopping_agent.data import load_products
from shopping_agent.models import SearchRequest
from shopping_agent.search import search_products


def show(title: str, request_data: dict, products: list) -> None:
    print(f"\n=== {title} ===")
    response = search_products(products, SearchRequest.model_validate(request_data))
    print(f"模式: {response.search_mode.value} | 商品池: {response.total_pool} | 完全满足: {response.filtered_count}")
    displayed = response.results or response.nearest_candidates
    for result in displayed:
        product = result.product
        print(f"{result.rank}. {product.brand} {product.model_name} | {product.price} 元 | {product.weight_kg}kg | 分数 {result.total_score:.3f}")
        if result.violations:
            print(f"   满足: {', '.join(result.satisfied_constraints) or '无'}")
            for violation in result.violations:
                print(f"   违反: {violation.message}；幅度={violation.magnitude:.3f}，成本={violation.weighted_cost:.3f}")


def main() -> None:
    products = load_products(Path(__file__).resolve().parents[1] / "data" / "products.jsonl")
    show("编程开发 + 预算 + 便携偏好", {
        "hard_constraints": {"budget_max": 7000, "ram_min": 16},
        "soft_preferences": {"scenarios": ["编程开发/数据分析"], "portability": "high"},
        "top_k": 5,
    }, products)
    show("游戏娱乐 + 独显 + 内存要求", {
        "hard_constraints": {"budget_max": 9000, "gpu_required": True, "ram_min": 16},
        "soft_preferences": {"scenarios": ["游戏娱乐"], "performance": "high"},
        "top_k": 5,
    }, products)
    show("冲突约束与 nearest 候选", {
        "hard_constraints": {
            "budget_max": {"value": 5000, "priority": "normal"},
            "gpu_required": {"value": True, "priority": "critical", "relaxable": False},
            "gpu_vram_min": 8,
            "weight_max": 1.0,
        },
        "soft_preferences": {"scenarios": ["AI/深度学习"]},
    }, products)


if __name__ == "__main__":
    main()
