"""Application settings.

All configuration is environment-driven so the same code runs locally
(SQLite) and in production (Supabase Postgres) without changes.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # Database. For Supabase use the connection string from
    # Project Settings -> Database, e.g.:
    #   postgresql+psycopg://postgres:<password>@db.<ref>.supabase.co:5432/postgres
    database_url: str = "sqlite:///./rein.db"

    # --- LLM provider selection -------------------------------------------
    # Chat assistant defaults to Ollama; extraction defaults to Anthropic.
    chat_llm_provider: Literal["anthropic", "ollama", "azure_openai"] = "ollama"
    extraction_llm_provider: Literal["anthropic", "ollama", "azure_openai"] = "anthropic"
    # Output-token ceiling for a single extraction. A long treaty plus a full
    # premium-rate table can produce a large structured response; too low a cap
    # truncates the tool-call JSON mid-way and fails schema validation. Current
    # Claude models allow up to 128K output (streaming required, which we enable
    # below), so give generous headroom. Raise further via LLM_MAX_TOKENS for
    # exceptionally large rate tables.
    llm_max_tokens: int = 32000
    # Long treaties can take minutes to extract. Streaming keeps the connection
    # alive (avoids "server disconnected" on long generations); the timeout and
    # retries add resilience to transient network drops.
    llm_streaming: bool = True
    llm_timeout_seconds: float = 600.0
    llm_max_retries: int = 3

    # Anthropic (Claude)
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-4-8"

    # Ollama (local models; no API key needed). Requires `pip install langchain-ollama`
    # and a running Ollama server. Pick a model that supports tools/structured
    # output, e.g. 'llama3.1', 'qwen2.5', 'mistral-nemo'.
    ollama_model: str = "llama3.1"
    ollama_base_url: str = "http://localhost:11434"

    # Azure OpenAI. Requires `pip install langchain-openai`. The deployment name
    # is your Azure deployment, not the base model name.
    azure_openai_api_key: SecretStr | None = None
    azure_openai_endpoint: str | None = None          # https://<resource>.openai.azure.com
    azure_openai_deployment: str | None = None        # your deployment name
    azure_openai_api_version: str = "2024-10-21"

    # --- Embeddings (Knowledge Base semantic search) ----------------------
    # Defaults to local Ollama (nothing leaves the box). Switch to azure_openai
    # to use a hosted text-embedding-3 deployment. Dimensions are locked to the
    # model the corpus was indexed with — changing model means reindexing.
    embeddings_provider: Literal["ollama", "azure_openai"] = "ollama"
    ollama_embed_model: str = "nomic-embed-text"
    azure_openai_embed_deployment: str | None = None  # your embeddings deployment name
    # How many treaty chunks to retrieve as context per question.
    rag_top_k: int = 6

    # Documents larger than this (characters) are truncated before being
    # sent to the LLM. Claude's 1M-token context comfortably covers full
    # treaties; this is a cost/safety backstop, not a functional limit.
    max_document_chars: int = 600_000

    # Reject uploads larger than this many bytes (guards memory + DB bloat).
    max_upload_bytes: int = 25 * 1024 * 1024  # 25 MB

    # --- Observability (MLflow) -------------------------------------------
    mlflow_enabled: bool = False
    mlflow_tracking_uri: str = "sqlite:///mlflow.db"
    mlflow_experiment: str = "treaty-extraction"


@lru_cache
def get_settings() -> Settings:
    return Settings()
