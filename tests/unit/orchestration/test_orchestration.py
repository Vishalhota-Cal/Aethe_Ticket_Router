"""
tests/unit/orchestration/test_orchestrator.py

Tests the orchestrator itself, using the mock LLM client (forced on in
conftest.py) rather than any real network call.
"""

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
    assert len(response.trace) == 3
    assert {step.agent_name for step in response.trace} == {
        "TriageAgent",
        "ValidationAgent",
        "ReviewAgent",
    }