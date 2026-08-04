"""Alibaba Cloud Model Studio adapter with JSON Mode and Pydantic validation."""

from __future__ import annotations

import json
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from shopping_agent.config import Settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class AIConfigurationError(RuntimeError):
    pass


class AIServiceError(RuntimeError):
    pass


class BailianProvider:
    """Call Qwen through Bailian's OpenAI-compatible Chat Completions API."""

    def __init__(self, settings: Settings, client: object | None = None) -> None:
        self.settings = settings
        if not settings.ai_enabled:
            raise AIConfigurationError(
                "AI 服务未配置：请设置 BAILIAN_API_KEY 后重新启动应用。"
            )
        self._client = client or OpenAI(
            api_key=settings.bailian_api_key,
            base_url=settings.bailian_base_url,
        )

    def parse_structured(
        self,
        *,
        system_prompt: str,
        user_input: str,
        schema: type[SchemaT],
    ) -> SchemaT:
        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n"
                    "请只输出合法 json，不要输出 Markdown 代码块或额外说明。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{user_input}\n\n输出必须符合以下 JSON Schema：\n{schema_text}"
                ),
            },
        ]
        try:
            response = self._client.chat.completions.create(
                model=self.settings.ai_model,
                messages=messages,
                response_format={"type": "json_object"},
                extra_body={"enable_thinking": False},
            )
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise AIServiceError("AI 返回了空的结构化结果。")
            return schema.model_validate_json(content)
        except AIServiceError:
            raise
        except Exception as exc:
            # Never include raw provider exceptions: they may contain request data.
            raise AIServiceError(
                "百炼千问 API 调用失败，请检查网络、模型权限或服务状态。"
            ) from exc
