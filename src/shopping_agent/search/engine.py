"""Hard filtering, scoring, diversity reranking, and nearest candidates."""

from __future__ import annotations

from typing import Any

from shopping_agent.models import (
    ConstraintItem,
    ConstraintPriority,
    ConstraintViolation,
    GPUType,
    Product,
    ProductSearchResult,
    SearchMode,
    SearchRequest,
    SearchResponse,
)
from shopping_agent.scoring.ranking import calculate_product_score

IMPORTANCE = {
    "gpu_required": 1.0, "budget_max": .9, "budget_min": .3,
    "ram_min": .7, "weight_max": .6, "screen_size_range": .5,
    "storage_min": .4, "gpu_vram_min": .8, "category": .8,
    "cpu_brand": .6, "required_ports": .7, "resolution_min": .5,
    "refresh_rate_min": .5, "brand": .8,
}


def _normalise_port(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _actual_value(product: Product, field: str) -> Any:
    mapping = {
        "budget_max": product.price, "budget_min": product.price,
        "gpu_required": product.gpu_type == GPUType.DISCRETE,
        "gpu_vram_min": product.gpu_vram_gb or 0, "ram_min": product.ram_gb,
        "storage_min": product.storage_capacity, "weight_max": product.weight_kg,
        "screen_size_range": product.screen_size, "resolution_min": product.resolution,
        "refresh_rate_min": product.refresh_rate or 0, "cpu_brand": product.cpu_brand,
        "category": product.product_category.value, "required_ports": product.ports,
        "brand": product.brand,
    }
    return mapping[field]


def _is_satisfied(product: Product, field: str, expected: Any) -> bool:
    actual = _actual_value(product, field)
    if field == "budget_max": return actual <= expected
    if field == "budget_min": return actual >= expected
    if field == "gpu_required": return actual is expected
    if field in {"gpu_vram_min", "ram_min", "storage_min", "refresh_rate_min"}: return actual >= expected
    if field == "weight_max": return actual <= expected
    if field == "screen_size_range": return expected[0] <= actual <= expected[1]
    if field == "resolution_min":
        actual_pair = tuple(int(part) for part in actual.split("x"))
        expected_pair = tuple(int(part) for part in expected.split("x"))
        return actual_pair[0] >= expected_pair[0] and actual_pair[1] >= expected_pair[1]
    if field in {"cpu_brand", "category"}: return str(actual).casefold() == str(expected).casefold()
    if field == "brand": return str(actual).casefold() in {str(item).casefold() for item in expected}
    if field == "required_ports":
        available = [_normalise_port(port) for port in actual]
        return all(any(_normalise_port(required) in port for port in available) for required in expected)
    raise ValueError(f"unsupported constraint: {field}")


def _magnitude(product: Product, field: str, expected: Any) -> float:
    actual = _actual_value(product, field)
    if field in {"budget_max", "weight_max"}:
        raw = (actual - expected) / max(abs(float(expected)), 1.0)
    elif field in {"budget_min", "gpu_vram_min", "ram_min", "storage_min", "refresh_rate_min"}:
        raw = (expected - actual) / max(abs(float(expected)), 1.0)
    elif field == "screen_size_range":
        lower, upper = expected
        distance = lower - actual if actual < lower else actual - upper
        span = upper - lower
        raw = abs(distance) if span == 0 else distance / span
    elif field == "required_ports":
        available = [_normalise_port(port) for port in actual]
        missing = sum(not any(_normalise_port(req) in port for port in available) for req in expected)
        raw = missing / max(len(expected), 1)
    elif field == "resolution_min":
        aw, ah = (int(part) for part in actual.split("x"))
        ew, eh = (int(part) for part in expected.split("x"))
        raw = max((ew - aw) / max(ew, 1), (eh - ah) / max(eh, 1), 0.0)
    else:
        raw = 1.0
    return min(max(float(raw), 0.0), 2.0)


def _check_product(product: Product, request: SearchRequest) -> tuple[dict[str, str], list[ConstraintViolation], list[str]]:
    checks: dict[str, str] = {}
    violations: list[ConstraintViolation] = []
    satisfied: list[str] = []
    for field, item in request.hard_constraints.active_items():
        if _is_satisfied(product, field, item.value):
            checks[field] = "pass"
            satisfied.append(field)
            continue
        checks[field] = "fail"
        magnitude = _magnitude(product, field, item.value)
        multiplier = 2.0 if item.priority == ConstraintPriority.CRITICAL else .5 if item.priority == ConstraintPriority.RELAXABLE else 1.0
        weighted_cost = IMPORTANCE[field] * magnitude * multiplier
        actual = _actual_value(product, field)
        violations.append(ConstraintViolation(
            field=field, constraint_value=item.value, actual_value=actual,
            magnitude=magnitude, weighted_cost=weighted_cost,
            priority=item.priority, relaxable=item.relaxable,
            is_critical=item.priority == ConstraintPriority.CRITICAL or not item.relaxable,
            message=f"{field}: 要求 {item.value!r}，实际 {actual!r}",
        ))
    return checks, violations, satisfied


def _diversity_rerank(results: list[ProductSearchResult], top_k: int) -> list[ProductSearchResult]:
    selected: list[ProductSearchResult] = []
    deferred: list[ProductSearchResult] = []
    brand_counts: dict[str, int] = {}
    for result in results:
        count = brand_counts.get(result.product.brand, 0)
        if count < 2:
            selected.append(result)
            brand_counts[result.product.brand] = count + 1
        else:
            deferred.append(result)
        if len(selected) == top_k:
            break
    if len(selected) < top_k:
        selected.extend(deferred[: top_k - len(selected)])
    return selected


def _ranked_result(product: Product, request: SearchRequest) -> ProductSearchResult:
    score, scores = calculate_product_score(product, request.soft_preferences)
    checks, violations, satisfied = _check_product(product, request)
    return ProductSearchResult(
        sku_id=product.sku_id, product=product, rank=1, total_score=score,
        dimension_scores=scores, constraint_check=checks, violations=violations,
        satisfied_constraints=satisfied,
        violation_cost=sum(violation.weighted_cost for violation in violations),
    )


def search_products(products: list[Product], request: SearchRequest) -> SearchResponse:
    """Search an in-memory product pool with no model or retrieval dependency."""
    ranked = [_ranked_result(product, request) for product in products]
    exact = [result for result in ranked if not result.violations]

    if request.search_mode == SearchMode.NORMAL and exact:
        exact.sort(key=lambda item: (-item.total_score, item.sku_id))
        hard_brand = request.hard_constraints.brand is not None
        if request.diversity_rerank and not hard_brand:
            exact = _diversity_rerank(exact, request.top_k)
        else:
            exact = exact[: request.top_k]
        for rank, result in enumerate(exact, start=1):
            result.rank = rank
        return SearchResponse(
            results=exact, filtered_count=len([item for item in ranked if not item.violations]),
            total_pool=len(products), search_mode=SearchMode.NORMAL,
        )

    # Explicit nearest mode, or automatic fallback when normal filtering is empty.
    violating = [result for result in ranked if result.violations]
    violating.sort(key=lambda item: (
        len(item.violations),
        any(violation.is_critical for violation in item.violations),
        item.violation_cost,
        -item.total_score,
        item.sku_id,
    ))
    nearest = violating[:2]
    for rank, result in enumerate(nearest, start=1):
        result.rank = rank
    return SearchResponse(
        results=[], nearest_candidates=nearest, filtered_count=len(exact),
        total_pool=len(products), search_mode=SearchMode.NEAREST,
    )

