"""Application settings.

All configuration is environment-driven so the same code runs locally
(SQLite) and in production (Supabase Postgres) without changes.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database. For Supabase use the connection string from
    # Project Settings -> Database, e.g.:
    #   postgresql+psycopg://postgres:<password>@db.<ref>.supabase.co:5432/postgres
    database_url: str = "sqlite:///./rein.db"

    # LLM used for extraction. Requires ANTHROPIC_API_KEY in the environment.
    anthropic_model: str = "claude-opus-4-8"
    llm_max_tokens: int = 16000

    # Documents larger than this (characters) are truncated before being
    # sent to the LLM. Claude's 1M-token context comfortably covers full
    # treaties; this is a cost/safety backstop, not a functional limit.
    max_document_chars: int = 600_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
