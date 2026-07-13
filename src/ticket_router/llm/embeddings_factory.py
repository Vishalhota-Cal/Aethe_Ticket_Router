"""
llm/embeddings_factory.py

Decides which embeddings provider gets used, based on Settings --
mirrors llm/factory.py exactly. Reuses LLM_PROVIDER so mock mode gets
free/offline embeddings and openai mode gets real ones, with no extra
env var required.
"""

from ticket_router.config.settings import get_settings
from ticket_router.llm.embeddings_client import EmbeddingsClient
from ticket_router.llm.mock_embeddings_client import MockEmbeddingsClient
from ticket_router.llm.openai_embeddings_client import OpenAIEmbeddingsClient


def get_embeddings_client() -> EmbeddingsClient:
    """Return the embeddings provider that should be used right now,
    chosen by the same LLM_PROVIDER setting the main LLM client uses.
    """
    settings = get_settings()

    if settings.llm_provider == "mock":
        return MockEmbeddingsClient()

    if settings.llm_provider == "openai":
        return OpenAIEmbeddingsClient(api_key=settings.openai_api_key, model=settings.embedding_model)

    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")