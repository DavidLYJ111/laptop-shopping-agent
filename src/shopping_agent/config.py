"""Environment configuration and stable project paths."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
WEB_DIR = PROJECT_ROOT / "web"


@dataclass(frozen=True)
class Settings:
    """Runtime settings. The API key is deliberately excluded from repr output."""

    openai_api_key: str | None = field(default=None, repr=False)
    openai_model: str = "gpt-5-mini"
    app_env: str = "development"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())


def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        app_env=os.getenv("APP_ENV", "development"),
    )

