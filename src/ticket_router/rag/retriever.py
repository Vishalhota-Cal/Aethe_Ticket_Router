"""
rag/retriever.py

The actual "R" in RAG: given the current ticket's embedding, finds the
most similar previously-routed tickets (by cosine similarity against
embeddings already saved in SQLite) and returns them as reference
context. Pure, framework-free function -- no AI call happens here,
only vector math against whatever the repository already has.
"""

import json
from typing import List, Optional

import numpy as np

from ticket_router.domain.models import RetrievedTicket
from ticket_router.persistence.repository import TicketRepository


def find_similar_tickets(
    query_embedding: List[float],
    repository: TicketRepository,
    top_k: int = 3,
    exclude_ticket_id: Optional[str] = None,
) -> List[RetrievedTicket]:
    """Return up to `top_k` past tickets most similar to
    `query_embedding`, ranked by cosine similarity. Returns an empty
    list if the knowledge base is empty -- there's nothing wrong with
    that, it just means this is one of the first tickets ever routed.
    """
    records = repository.get_all_with_embeddings()
    if not records:
        return []

    query = np.array(query_embedding, dtype=float)
    query_norm = np.linalg.norm(query)
    if query_norm == 0:
        return []

    scored = []
    for record in records:
        if exclude_ticket_id is not None and record.id == exclude_ticket_id:
            continue

        vector = np.array(json.loads(record.embedding), dtype=float)
        vector_norm = np.linalg.norm(vector)
        if vector_norm == 0:
            continue

        similarity = float(np.dot(query, vector) / (query_norm * vector_norm))
        scored.append((similarity, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    return [
        RetrievedTicket(
            ticket_id=record.id,
            subject=record.subject,
            category=record.category,
            priority=record.priority,
            assigned_team=record.assigned_team,
            similarity_score=round(similarity, 3),
        )
        for similarity, record in scored[:top_k]
    ]