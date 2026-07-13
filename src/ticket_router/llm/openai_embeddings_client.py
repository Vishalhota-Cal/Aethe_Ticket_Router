"""
llm/openai_embeddings_client.py

The real embeddings provider, using OpenAI's embeddings API. Same
LLMProviderError-wrapping convention as openai_client.py, so this
plugs into the existing retry/resilience machinery for free.
"""

from typing import List

from openai import AsyncOpenAI

from ticket_router.domain.exceptions import LLMProviderError


class OpenAIEmbeddingsClient:
    """Sends text to a real OpenAI embeddings model and returns the
    resulting vector.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed(self, text: str) -> List[float]:
        try:
            response = await self._client.embeddings.create(model=self._model, input=text)
            return response.data[0].embedding

        except Exception as error:
            raise LLMProviderError(f"OpenAI embeddings request failed: {error}") from error