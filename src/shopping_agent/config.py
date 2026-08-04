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

    bailian_api_key: str | None = field(default=None, repr=False)
    ai_model: str = "qwen-plus"
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    app_env: str = "development"

    @property
    def ai_enabled(self) -> bool:
        key = (self.bailian_api_key or "").strip()
        return bool(key and not key.startswith(("your_", "请在这里")))


def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    return Settings(
        bailian_api_key=os.getenv("BAILIAN_API_KEY"),
        ai_model=os.getenv("AI_MODEL", "qwen-plus"),
        bailian_base_url=os.getenv(
            "BAILIAN_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        app_env=os.getenv("APP_ENV", "development"),
    )
