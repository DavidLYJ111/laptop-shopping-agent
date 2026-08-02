from pathlib import Path

import pytest

from shopping_agent.data import load_products


@pytest.fixture(scope="session")
def products():
    return load_products(Path(__file__).resolve().parents[1] / "data" / "products.jsonl")

