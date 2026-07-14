"""
tests/unit/orchestration/test_orchestrator.py

Tests the orchestrator itself, using the mock LLM client (forced on in
conftest.py) rather than any real network call.
"""

from ticket_router.domain.exceptions import LLMProviderError
from ticket_router.domain.models import Ticket
from ticket_router.orchestration.orchestrator import TicketRoutingOrchestrator


async def test_route_returns_a_full_response_for_a_normal_ticket():
    orchestrator = TicketRoutingOrchestrator()
    ticket = Ticket(
        id="1",
        subject="Can't log in",
        description="I've been locked out and need this fixed immediately.",
    )

    response = await orchestrator.route(ticket=ticket, correlation_id="test-corr-id")

    assert response.result.category is not None
    assert 0 <= response.result.confidence_score <= 100
    assert len(response.trace) == 4
    assert {step.agent_name for step in response.trace} == {
        "RetrievalAgent",
        "TriageAgent",
        "ValidationAgent",
        "ReviewAgent",
    }


class _AlwaysDownClient:
    """Stands in for a fully unreachable AI provider -- an invalid API
    key, an expired key, or a network outage all surface the same way:
    every call raises LLMProviderError, with no successful attempt ever
    possible. Used to prove routing degrades gracefully instead of
    crashing (mission criterion M4B3).
    """

    async def complete(self, prompt: str) -> str:
        raise LLMProviderError("simulated: invalid API key / provider unreachable")


async def test_route_degrades_gracefully_when_llm_provider_is_unreachable(monkeypatch):
    # Patch the factory function exactly where TriageAgent looks it up,
    # so every retry attempt inside call_with_retry still fails, the
    # same way a genuinely dead API key would.
    monkeypatch.setattr(
        "ticket_router.agents.triage_agent.get_llm_client",
        lambda: _AlwaysDownClient(),
    )

    orchestrator = TicketRoutingOrchestrator()
    ticket = Ticket(
        id="outage-1",
        subject="Can't log in",
        description="I've been locked out and need this fixed immediately.",
    )

    # The key assertion: this must NOT raise. A dead AI provider should
    # degrade to a safe, human-flagged result -- never an unhandled 500.
    response = await orchestrator.route(ticket=ticket, correlation_id="test-outage")

    assert response.result.needs_human_review is True
    assert response.result.confidence_score == 0
    assert response.result.category.value == "General"
    # TriageAgent's failed attempt should still show up in the trace --
    # the mentor should be able to see *that* it failed, not just that
    # the system silently recovered.
    triage_steps = [step for step in response.trace if step.agent_name == "TriageAgent"]
    assert len(triage_steps) == 1
    assert triage_steps[0].success is False