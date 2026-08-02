from shopping_agent.models import SearchRequest
from shopping_agent.search import search_products


def request(**data):
    return SearchRequest.model_validate(data)


def test_single_budget_filter(products):
    response = search_products(products, request(hard_constraints={"budget_max": 6000}))
    assert response.results
    assert all(result.product.price <= 6000 for result in response.results)


def test_multiple_hard_constraints(products):
    response = search_products(products, request(hard_constraints={
        "budget_max": 8000, "gpu_required": True, "ram_min": 32,
        "storage_min": 1024, "weight_max": 2.0,
    }))
    assert {result.sku_id for result in response.results} == {
        "dell_inspiron16_mock_32_1024_4050", "acer_swiftx14_mock_32_1024_4050"
    }


def test_required_ports_list_filter(products):
    response = search_products(products, request(hard_constraints={
        "required_ports": ["Thunderbolt 4", "HDMI"]
    }))
    assert response.results
    assert all(any("thunderbolt 4" in port.lower() for port in result.product.ports) for result in response.results)
    assert all(any("hdmi" in port.lower() for port in result.product.ports) for result in response.results)


def test_fuzzy_preference_is_not_hard_constraint(products):
    response = search_products(products, request(soft_preferences={"portability": "high"}))
    assert response.filtered_count == len(products)
    assert any(result.product.weight_kg > 1.5 for result in response.results)


def test_normal_mode_sorted_descending(products):
    response = search_products(products, request(soft_preferences={"scenarios": ["游戏娱乐"]}, diversity_rerank=False))
    scores = [result.total_score for result in response.results]
    assert scores == sorted(scores, reverse=True)


def test_scene_weights_change_order(products):
    office = search_products(products, request(soft_preferences={"scenarios": ["办公学习"]}, top_k=10, diversity_rerank=False))
    gaming = search_products(products, request(soft_preferences={"scenarios": ["游戏娱乐"]}, top_k=10, diversity_rerank=False))
    assert [item.sku_id for item in office.results] != [item.sku_id for item in gaming.results]
    gaming_ids = [item.sku_id for item in gaming.results]
    office_ids = [item.sku_id for item in office.results]
    assert gaming_ids.index("lenovo_legion15_mock_32_1024_4060") < office_ids.index("lenovo_legion15_mock_32_1024_4060")


def test_soft_brand_preference_improves_rank(products):
    base = search_products(products, request(top_k=10, diversity_rerank=False))
    preferred = search_products(products, request(soft_preferences={"brand": ["苹果"]}, top_k=10, diversity_rerank=False))
    base_rank = next(item.rank for item in base.results if item.product.brand == "苹果")
    preferred_rank = next(item.rank for item in preferred.results if item.product.brand == "苹果")
    assert preferred_rank < base_rank


def test_brand_diversity_rerank(products):
    template = products[1]
    synthetic = [template.model_copy(update={"sku_id": f"same_brand_{index}", "model_name": f"Same {index}"}) for index in range(4)]
    synthetic.extend(products[2:7])
    response = search_products(synthetic, request(top_k=5))
    assert sum(item.product.brand == template.brand for item in response.results) <= 2


def test_empty_normal_result_falls_back_to_nearest(products):
    response = search_products(products, request(hard_constraints={
        "budget_max": 3000, "gpu_required": True, "weight_max": 1.0
    }))
    assert response.search_mode.value == "nearest"
    assert response.results == []
    assert 1 <= len(response.nearest_candidates) <= 2
    assert all(candidate.violations for candidate in response.nearest_candidates)


def test_nearest_results_never_appear_as_normal_results(products):
    response = search_products(products, request(search_mode="nearest", hard_constraints={"budget_max": 6000}))
    assert response.results == []
    assert response.nearest_candidates
    assert all(candidate.product.price > 6000 for candidate in response.nearest_candidates)


def test_critical_violation_is_deprioritized_when_counts_tie(products):
    low_price_heavy = products[0].model_copy(update={"sku_id": "low_price_heavy", "price": 5000, "weight_kg": 2.0})
    high_price_light = products[1].model_copy(update={"sku_id": "high_price_light", "price": 8000, "weight_kg": 1.0})
    response = search_products([low_price_heavy, high_price_light], request(
        search_mode="nearest",
        hard_constraints={
            "budget_max": {"value": 6000, "priority": "critical", "relaxable": False},
            "weight_max": 1.5,
        },
    ))
    assert response.nearest_candidates[0].sku_id == "low_price_heavy"
    assert not response.nearest_candidates[0].violations[0].is_critical
    assert response.nearest_candidates[1].violations[0].is_critical


def test_violation_magnitude_and_cap(products):
    product = products[0].model_copy(update={"sku_id": "price_test", "price": 9000})
    response = search_products([product], request(hard_constraints={"budget_max": 6000}))
    violation = response.nearest_candidates[0].violations[0]
    assert violation.magnitude == 0.5
    zero = search_products([product], request(search_mode="nearest", hard_constraints={"budget_max": 0}))
    assert zero.nearest_candidates[0].violations[0].magnitude == 2.0


def test_single_point_screen_range_has_no_division_by_zero(products):
    response = search_products(products, request(search_mode="nearest", hard_constraints={"screen_size_range": [14.0, 14.0]}))
    assert response.nearest_candidates
    assert all(0 <= item.violations[0].magnitude <= 2 for item in response.nearest_candidates)

