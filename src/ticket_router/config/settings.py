"""
config/settings.py

Centralizes every environment-specific value the app needs, read once
from a .env file. Nothing elsewhere in the codebase should read
environment variables directly anymore -- everything goes through this
Settings object instead.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "mock"
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    database_url: str = "sqlite:///./ticket_router.db"
    max_repair_attempts: int = 2
    confidence_threshold: int = 70
    rag_top_k: int = 3


@lru_cache
def get_settings() -> Settings:
    """Build the Settings object once, then reuse the same instance
    everywhere instead of re-reading .env on every call.
    """
    return Settings()