"""
tests/unit/rag/test_retriever.py

Proves the cosine-similarity ranking in rag/retriever.py actually
ranks a genuinely similar past ticket above an unrelated one -- not
just that it runs without crashing. Uses a fake repository so this
test needs no real database or embeddings API call.
"""

import json
from types import SimpleNamespace

from ticket_router.rag.retriever import find_similar_tickets


class FakeRepository:
    def __init__(self, records):
        self._records = records

    def get_all_with_embeddings(self):
        return self._records


def make_record(ticket_id, embedding, category="Billing"):
    return SimpleNamespace(
        id=ticket_id,
        subject=f"Subject for {ticket_id}",
        category=category,
        priority="Medium",
        assigned_team="Billing Team",
        embedding=json.dumps(embedding),
    )


def test_ranks_closer_vector_above_unrelated_vector():
    close_match = make_record("close", [1.0, 1.0, 0.0])
    unrelated = make_record("far", [0.0, 0.0, 1.0], category="Security")
    repository = FakeRepository([close_match, unrelated])

    results = find_similar_tickets(
        query_embedding=[1.0, 1.0, 0.0],
        repository=repository,
        top_k=2,
    )

    assert results[0].ticket_id == "close"
    assert results[0].similarity_score > results[1].similarity_score
    assert results[0].similarity_score == 1.0


def test_excludes_the_ticket_itself():
    self_record = make_record("self-ticket", [1.0, 0.0])
    other = make_record("other", [1.0, 0.0])
    repository = FakeRepository([self_record, other])

    results = find_similar_tickets(
        query_embedding=[1.0, 0.0],
        repository=repository,
        top_k=5,
        exclude_ticket_id="self-ticket",
    )

    assert len(results) == 1
    assert results[0].ticket_id == "other"


def test_empty_knowledge_base_returns_empty_list():
    repository = FakeRepository([])
    results = find_similar_tickets(query_embedding=[1.0, 0.0], repository=repository)
    assert results == []