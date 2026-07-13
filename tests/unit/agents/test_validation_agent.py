"""
tests/unit/agents/test_validation_agent.py

Unit tests for ValidationAgent's parsing and repair-loop behavior,
using a tiny fake LLM client (monkeypatched in) instead of the real
mock/OpenAI clients, so these tests never touch the network.
"""

import json

import pytest

from ticket_router.agents.validation_agent import ValidationAgent
from ticket_router.domain.exceptions import ValidationFailedError
from ticket_router.domain.models import Ticket, TicketContext


def make_context(raw_response: str) -> TicketContext:
    ticket = Ticket(id="1", subject="s", description="d")
    context = TicketContext(ticket=ticket, correlation_id="test-id")
    context.raw_ai_response = raw_response
    return context


GOOD_JSON = json.dumps(
    {
        "category": "Technical",
        "priority": "High",
        "assigned_team": "IT Support",
        "reason": "test",
        "confidence_score": 90,
    }
)

BAD_JSON = json.dumps(
    {
        "category": "Technical",
        "priority": "High",
        "assigned_team": "IT Support",
        "reason": "test",
        "confidence_score": "very sure",
    }
)


async def test_valid_json_passes_on_first_try():
    context = make_context(GOOD_JSON)

    result = await ValidationAgent().execute(context)

    assert result.data.category.value == "Technical"
    assert context.repair_attempts == 0


async def test_bad_json_repairs_then_succeeds(monkeypatch):
    class FakeClient:
        async def complete(self, prompt: str) -> str:
            return GOOD_JSON

    monkeypatch.setattr(
        "ticket_router.agents.validation_agent.get_llm_client",
        lambda: FakeClient(),
    )

    context = make_context(BAD_JSON)
    result = await ValidationAgent().execute(context)

    assert result.data.confidence_score == 90
    assert context.repair_attempts == 1


async def test_gives_up_after_max_attempts(monkeypatch):
    class FakeClient:
        async def complete(self, prompt: str) -> str:
            return "not json at all"

    monkeypatch.setattr(
        "ticket_router.agents.validation_agent.get_llm_client",
        lambda: FakeClient(),
    )

    context = make_context("not json at all")

    with pytest.raises(ValidationFailedError):
        await ValidationAgent().execute(context)

    assert context.repair_attempts == 2