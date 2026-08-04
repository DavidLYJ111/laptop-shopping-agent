"""Vercel entry point for the FastAPI application.

The project uses a ``src`` layout.  Adding it to ``sys.path`` keeps the
deployment entry point explicit and also allows ``python app.py`` imports from
the repository root without requiring an editable installation.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shopping_agent.api.main import app  # noqa: E402

__all__ = ["app"]
