from __future__ import annotations

from apps.api.app.config import settings
from apps.api.app.services.llm.base import DisabledLLMClient, LLMClient
from apps.api.app.services.llm.gemini_client import GeminiClient


def get_llm_client() -> LLMClient:
    if settings.gemini_api_key:
        return GeminiClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.gemini_timeout_seconds,
        )
    return DisabledLLMClient()
