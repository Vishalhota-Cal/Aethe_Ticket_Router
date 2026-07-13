"""
llm/factory.py

Decides which AI provider actually gets used, based on Settings.
Nothing else in the codebase needs to know this decision is being
made -- it just asks this file for "the LLM client" and gets back
whichever one is currently configured.
"""

from ticket_router.config.settings import get_settings
from ticket_router.llm.client import LLMClient
from ticket_router.llm.mock_client import MockClient
from ticket_router.llm.openai_client import OpenAIClient


def get_llm_client() -> LLMClient:
    """Return the AI provider that should be used right now, chosen by
    settings.llm_provider (which comes from LLM_PROVIDER in .env).
    """
    settings = get_settings()

    if settings.llm_provider == "mock":
        return MockClient()

    if settings.llm_provider == "openai":
        return OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)

    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")