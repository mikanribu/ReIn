"""LLM factories.

Chat and extraction use separate provider settings so the app can keep a
local Ollama assistant while using Anthropic for treaty parsing.
Provider SDKs are imported lazily so you only need the packages you actually
use.
"""
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import Settings, get_settings


def _secret(value) -> str | None:
    if value is None:
        return None
    return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)


def _missing(pkg: str, provider: str) -> RuntimeError:
    return RuntimeError(
        f"LLM provider '{provider}' requires the '{pkg}' package. "
        f"Install it with: pip install {pkg}"
    )


def _build_anthropic(s: Settings, purpose: str) -> BaseChatModel:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:  # pragma: no cover - import guard
        raise _missing("langchain-anthropic", "anthropic") from exc
    key = _secret(s.anthropic_api_key)
    if not key:
        raise RuntimeError(f"ANTHROPIC_API_KEY must be set in .env or the environment for {purpose}")
    return ChatAnthropic(model=s.anthropic_model, api_key=key, max_tokens=s.llm_max_tokens)


def _build_ollama(s: Settings) -> BaseChatModel:
    try:
        from langchain_ollama import ChatOllama
    except ImportError as exc:  # pragma: no cover - import guard
        raise _missing("langchain-ollama", "ollama") from exc
    # Ollama runs locally; no API key. The model must support tool/structured
    # output for extraction to work (e.g. llama3.1, qwen2.5, mistral-nemo).
    return ChatOllama(model=s.ollama_model, base_url=s.ollama_base_url, num_predict=s.llm_max_tokens)


def _build_azure_openai(s: Settings) -> BaseChatModel:
    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError as exc:  # pragma: no cover - import guard
        raise _missing("langchain-openai", "azure_openai") from exc
    key = _secret(s.azure_openai_api_key)
    missing = [
        name for name, val in [
            ("AZURE_OPENAI_API_KEY", key),
            ("AZURE_OPENAI_ENDPOINT", s.azure_openai_endpoint),
            ("AZURE_OPENAI_DEPLOYMENT", s.azure_openai_deployment),
        ] if not val
    ]
    if missing:
        raise RuntimeError(f"Azure OpenAI provider requires: {', '.join(missing)}")
    return AzureChatOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        azure_deployment=s.azure_openai_deployment,
        api_version=s.azure_openai_api_version,
        api_key=key,
        max_tokens=s.llm_max_tokens,
    )


@lru_cache
def get_chat_model() -> BaseChatModel:
    settings = get_settings()
    provider = settings.chat_llm_provider.strip().lower()
    if provider == "anthropic":
        return _build_anthropic(settings, "chat")
    if provider == "ollama":
        return _build_ollama(settings)
    if provider == "azure_openai":
        return _build_azure_openai(settings)
    raise RuntimeError(
        f"Unknown CHAT_LLM_PROVIDER '{settings.chat_llm_provider}'. "
        "Valid options: anthropic, ollama, azure_openai."
    )


@lru_cache
def get_extraction_model() -> BaseChatModel:
    settings = get_settings()
    provider = settings.extraction_llm_provider.strip().lower()
    if provider == "anthropic":
        return _build_anthropic(settings, "extraction")
    if provider == "ollama":
        return _build_ollama(settings)
    if provider == "azure_openai":
        return _build_azure_openai(settings)
    raise RuntimeError(
        f"Unknown EXTRACTION_LLM_PROVIDER '{settings.extraction_llm_provider}'. "
        "Valid options: anthropic, ollama, azure_openai."
    )
