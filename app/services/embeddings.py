"""Embeddings factory for the Knowledge Base semantic index.

Mirrors the LLM factory: provider-agnostic, lazy imports, selected by
EMBEDDINGS_PROVIDER. Returns an object with the LangChain embeddings interface
(``embed_documents`` / ``embed_query``) plus a stable ``model_id`` used to tag
stored vectors, so a corpus indexed with one model is never mixed with another.
"""
from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings


def _secret(value) -> str | None:
    if value is None:
        return None
    return value.get_secret_value() if hasattr(value, "get_secret_value") else str(value)


@dataclass
class Embedder:
    """Thin wrapper pairing a LangChain embeddings client with its model id."""

    client: object
    model_id: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.client.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self.client.embed_query(text)


def _build_ollama(s: Settings) -> Embedder:
    try:
        from langchain_ollama import OllamaEmbeddings
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "Embeddings provider 'ollama' requires 'langchain-ollama'. "
            "Install it with: pip install langchain-ollama"
        ) from exc
    client = OllamaEmbeddings(model=s.ollama_embed_model, base_url=s.ollama_base_url)
    return Embedder(client=client, model_id=f"ollama:{s.ollama_embed_model}")


def _build_azure(s: Settings) -> Embedder:
    try:
        from langchain_openai import AzureOpenAIEmbeddings
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "Embeddings provider 'azure_openai' requires 'langchain-openai'. "
            "Install it with: pip install langchain-openai"
        ) from exc
    key = _secret(s.azure_openai_api_key)
    missing = [
        name for name, val in [
            ("AZURE_OPENAI_API_KEY", key),
            ("AZURE_OPENAI_ENDPOINT", s.azure_openai_endpoint),
            ("AZURE_OPENAI_EMBED_DEPLOYMENT", s.azure_openai_embed_deployment),
        ] if not val
    ]
    if missing:
        raise RuntimeError(f"Azure embeddings require: {', '.join(missing)}")
    client = AzureOpenAIEmbeddings(
        azure_endpoint=s.azure_openai_endpoint,
        azure_deployment=s.azure_openai_embed_deployment,
        api_version=s.azure_openai_api_version,
        api_key=key,
    )
    return Embedder(client=client, model_id=f"azure:{s.azure_openai_embed_deployment}")


@lru_cache
def get_embeddings() -> Embedder:
    settings = get_settings()
    provider = settings.embeddings_provider.strip().lower()
    if provider == "ollama":
        return _build_ollama(settings)
    if provider == "azure_openai":
        return _build_azure(settings)
    raise RuntimeError(
        f"Unknown EMBEDDINGS_PROVIDER '{settings.embeddings_provider}'. "
        "Valid options: ollama, azure_openai."
    )
