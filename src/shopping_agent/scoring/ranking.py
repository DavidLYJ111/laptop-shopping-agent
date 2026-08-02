"""Reproducible scene templates and product dimension scoring."""

from __future__ import annotations

from shopping_agent.models import PreferenceLevel, Product, SoftPreferences

DEFAULT_WEIGHTS = {
    "cpu": 1 / 6,
    "gpu": 1 / 6,
    "ram": 1 / 6,
    "battery": 1 / 6,
    "weight": 1 / 6,
    "price": 1 / 6,
}

SCENE_WEIGHTS: dict[str, dict[str, float]] = {
    "办公学习": {"cpu": .20, "gpu": .05, "ram": .25, "battery": .30, "weight": .15, "price": .05},
    "编程开发/数据分析": {"cpu": .25, "gpu": .10, "ram": .30, "battery": .15, "weight": .10, "price": .10},
    "AI/深度学习": {"cpu": .15, "gpu": .35, "ram": .30, "battery": .05, "weight": .05, "price": .10},
    "游戏娱乐": {"cpu": .20, "gpu": .35, "ram": .15, "battery": .10, "weight": .05, "price": .15},
    "视频剪辑/设计创作": {"cpu": .20, "gpu": .30, "ram": .25, "battery": .10, "weight": .05, "price": .10},
}

SCENE_ALIASES = {
    "办公": "办公学习", "学习": "办公学习",
    "编程开发": "编程开发/数据分析", "编程": "编程开发/数据分析", "数据分析": "编程开发/数据分析",
    "AI": "AI/深度学习", "深度学习": "AI/深度学习",
    "游戏": "游戏娱乐",
    "视频剪辑": "视频剪辑/设计创作", "设计创作": "视频剪辑/设计创作", "设计": "视频剪辑/设计创作",
}

PREFERENCE_BOOST = {
    PreferenceLevel.LOW: -0.2,
    PreferenceLevel.MEDIUM: 0.0,
    PreferenceLevel.HIGH: 0.3,
}


def _scene_name(scenarios: list[str]) -> str | None:
    for scenario in scenarios:
        if scenario in SCENE_WEIGHTS:
            return scenario
        if scenario in SCENE_ALIASES:
            return SCENE_ALIASES[scenario]
        for alias, canonical in SCENE_ALIASES.items():
            if alias.lower() in scenario.lower():
                return canonical
    return None


def calculate_weights(preferences: SoftPreferences) -> dict[str, float]:
    scene = _scene_name(preferences.scenarios)
    weights = dict(SCENE_WEIGHTS.get(scene, DEFAULT_WEIGHTS))

    adjustments = {
        "weight": preferences.portability,
        "battery": preferences.battery_life,
        "price": preferences.value_for_money,
    }
    for dimension, preference in adjustments.items():
        if preference is not None:
            weights[dimension] *= 1 + PREFERENCE_BOOST[preference]

    if preferences.performance is not None:
        boost = 1 + PREFERENCE_BOOST[preferences.performance]
        for dimension in ("cpu", "gpu", "ram"):
            weights[dimension] *= boost

    total = sum(weights.values())
    if total <= 0:  # Defensive guard; current fixed mappings cannot reach zero.
        return dict(DEFAULT_WEIGHTS)
    return {name: value / total for name, value in weights.items()}


def dimension_scores(product: Product) -> dict[str, float]:
    ram_score = min(max((product.ram_gb - 8) / 56, 0.0), 1.0)
    performance = (
        product.cpu_performance_score * .45
        + product.gpu_performance_score * .35
        + ram_score * .20
    )
    # Fixed bounds avoid dataset-dependent ranking and guard against division by zero.
    price_efficiency = min(max(performance * 6000 / max(product.price, 1), 0.0), 1.0)
    return {
        "cpu": product.cpu_performance_score,
        "gpu": product.gpu_performance_score,
        "ram": ram_score,
        "battery": product.battery_capacity_score,
        "weight": product.portability_score,
        "price": price_efficiency,
    }


def calculate_product_score(
    product: Product, preferences: SoftPreferences
) -> tuple[float, dict[str, float]]:
    weights = calculate_weights(preferences)
    scores = dimension_scores(product)
    total = sum(weights[name] * scores[name] for name in weights)

    if preferences.brand and product.brand.casefold() in {brand.casefold() for brand in preferences.brand}:
        total += 0.08

    scene = _scene_name(preferences.scenarios)
    searchable = " ".join([product.scenario_desc, *product.tags, *product.selling_points]).casefold()
    if scene:
        keywords = {
            "办公学习": ("办公", "学习"),
            "编程开发/数据分析": ("编程", "开发", "数据分析"),
            "AI/深度学习": ("ai", "深度学习"),
            "游戏娱乐": ("游戏",),
            "视频剪辑/设计创作": ("剪辑", "设计", "创作"),
        }[scene]
        if any(keyword.casefold() in searchable for keyword in keywords):
            total += 0.04

    return min(max(total, 0.0), 1.0), scores

