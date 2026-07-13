"""
llm/mock_embeddings_client.py

A deterministic, offline stand-in for a real embeddings API -- so RAG
can be developed, tested, and demoed with LLM_PROVIDER=mock, at zero
cost and no network calls, exactly like mock_client.py does for the
main LLM.

This is a classic "feature hashing" bag-of-words embedding: every word
in the text is hashed into one of VECTOR_DIM buckets and counted, then
the vector is L2-normalized. It is not a semantic embedding (it can't
tell "car" and "vehicle" are related), but it genuinely rewards shared
vocabulary -- two tickets both mentioning "invoice" and "refund" really
do end up close together in this vector space -- which is enough to
prove the retrieval/cosine-similarity mechanics end to end without an
API key.
"""

import hashlib
import re
from typing import List

VECTOR_DIM = 256


class MockEmbeddingsClient:
    """Hashes words into a fixed-length vector -- deterministic, free,
    and offline, but still a real (if crude) embedding.
    """

    async def embed(self, text: str) -> List[float]:
        vector = [0.0] * VECTOR_DIM
        words = re.findall(r"[a-z0-9']+", text.lower())

        for word in words:
            bucket = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16) % VECTOR_DIM
            vector[bucket] += 1.0

        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector