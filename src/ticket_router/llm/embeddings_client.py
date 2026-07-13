"""
llm/embeddings_client.py

The contract every embeddings provider must follow -- mirrors
llm/client.py's LLMClient pattern exactly (one async method, text in,
vector out), so RetrievalAgent never needs to know whether it's talking
to the mock hashing embedder or a real OpenAI embeddings model.
"""

from typing import List, Protocol


class EmbeddingsClient(Protocol):
    """Any class acting as an embeddings provider must implement this
    one method, with exactly this shape.
    """

    async def embed(self, text: str) -> List[float]:
        """Return a fixed-length numeric vector representing `text`."""
        ...