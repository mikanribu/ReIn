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
    kwargs: dict = {
        "model": settings.anthropic_model,
        "max_tokens": settings.llm_max_tokens,
        # Structured output below uses forced tool calling; we deliberately do
        # not set sampling parameters (removed on current Opus-tier models).
    }
    # Pass the key explicitly when configured (env var or .env); otherwise let
    # the SDK resolve it from the environment.
    if settings.anthropic_api_key:
        kwargs["api_key"] = settings.anthropic_api_key
    return ChatAnthropic(**kwargs)
