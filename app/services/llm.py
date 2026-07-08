"""LLM factory.

The chat model is created here and nowhere else, so switching providers
(Anthropic / Ollama / Azure OpenAI) is driven entirely by configuration and
the rest of the app is untouched. Extraction calls ``.with_structured_output``
on whatever model this returns, which every supported provider implements.

Provider is chosen by ``LLM_PROVIDER`` (see app/config.py). Provider SDKs are
imported lazily so you only need the packages for the provider you use.
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
        f"LLM_PROVIDER='{provider}' requires the '{pkg}' package. "
        f"Install it with: pip install {pkg}"
    )


def _build_anthropic(s: Settings) -> BaseChatModel:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:  # pragma: no cover - import guard
        raise _missing("langchain-anthropic", "anthropic") from exc
    key = _secret(s.anthropic_api_key)
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set in .env or the environment")
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
        raise RuntimeError(f"LLM_PROVIDER='azure_openai' requires: {', '.join(missing)}")
    return AzureChatOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        azure_deployment=s.azure_openai_deployment,
        api_version=s.azure_openai_api_version,
        api_key=key,
        max_tokens=s.llm_max_tokens,
    )


_BUILDERS = {
    "anthropic": _build_anthropic,
    "ollama": _build_ollama,
    "azure_openai": _build_azure_openai,
}


@lru_cache
def get_chat_model() -> BaseChatModel:
    settings = get_settings()
    provider = settings.llm_provider.strip().lower()
    builder = _BUILDERS.get(provider)
    if builder is None:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER '{settings.llm_provider}'. "
            f"Valid options: {', '.join(sorted(_BUILDERS))}."
        )
    return builder(settings)
