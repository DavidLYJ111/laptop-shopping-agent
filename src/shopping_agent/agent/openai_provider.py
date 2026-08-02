"""Official OpenAI Responses API adapter with Pydantic Structured Outputs."""

from __future__ import annotations

from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from shopping_agent.config import Settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class AIConfigurationError(RuntimeError):
    pass


class AIServiceError(RuntimeError):
    pass


class OpenAIProvider:
    """Make one structured Responses API call per requested stage."""

    def __init__(self, settings: Settings, client: object | None = None) -> None:
        self.settings = settings
        if not settings.ai_enabled:
            raise AIConfigurationError(
                "AI 服务未配置：请设置 OPENAI_API_KEY 后重新启动应用。"
            )
        self._client = client or OpenAI(api_key=settings.openai_api_key)

    def parse_structured(
        self,
        *,
        system_prompt: str,
        user_input: str,
        schema: type[SchemaT],
    ) -> SchemaT:
        try:
            response = self._client.responses.parse(
                model=self.settings.openai_model,
                instructions=system_prompt,
                input=user_input,
                text_format=schema,
                store=False,
            )
            parsed = response.output_parsed
            if parsed is None:
                raise AIServiceError("AI 返回了空的结构化结果。")
            return schema.model_validate(parsed)
        except AIServiceError:
            raise
        except Exception as exc:
            # Deliberately exclude the raw SDK exception: it can contain request data.
            raise AIServiceError(
                "OpenAI API 调用失败，请检查网络、模型权限或服务状态。"
            ) from exc
