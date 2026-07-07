"""LLM factory.

The chat model is created here and nowhere else, so swapping models (or
mocking in tests via FastAPI dependency overrides) is a one-line change.
"""
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings


@lru_cache
def get_chat_model() -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    settings = get_settings()
    return ChatAnthropic(
        model=settings.anthropic_model,
        max_tokens=settings.llm_max_tokens,
        # Structured output below uses forced tool calling; we deliberately do
        # not set sampling parameters (removed on current Opus-tier models).
    )
