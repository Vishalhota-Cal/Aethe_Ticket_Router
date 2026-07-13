"""
tests/unit/orchestration/test_edge_cases.py

Proves the three edge cases explicitly required by the mission brief
are handled sensibly end to end: an angry ticket, a very short ticket,
and an ambiguous ticket that could belong to more than one category.
Runs through the real orchestrator (mock LLM, forced on in conftest.py).
"""

from ticket_router.domain.models import Ticket
from ticket_router.orchestration.orchestrator import TicketRoutingOrchestrator


async def test_angry_tone_ticket_is_flagged_for_human_review():
    orchestrator = TicketRoutingOrchestrator()
    ticket = Ticket(
        id="edge-1",
        subject="This is ridiculous",
        description=(
            "I've been on hold for hours and no one has helped me. "
            "This is completely unacceptable, fix this now!!!"
        ),
    )

    response = await orchestrator.route(ticket=ticket, correlation_id="edge-angry")

    assert response.result.sentiment.value == "Angry"
    assert response.result.priority.value == "High"
    assert response.result.needs_human_review is True


async def test_very_short_message_gets_low_confidence_and_review():
    orchestrator = TicketRoutingOrchestrator()
    ticket = Ticket(id="edge-2", subject="Help", description="Broken.")

    response = await orchestrator.route(ticket=ticket, correlation_id="edge-short")

    assert response.result.confidence_score < 70
    assert response.result.needs_human_review is True


async def test_ambiguous_ticket_matching_multiple_categories_gets_low_confidence():
    orchestrator = TicketRoutingOrchestrator()
    ticket = Ticket(
        id="edge-3",
        subject="Not sure who handles this",
        description=(
            "I was charged twice on my last invoice and now I can't log into "
            "my account to check it -- not sure if this is billing or technical."
        ),
    )

    response = await orchestrator.route(ticket=ticket, correlation_id="edge-ambiguous")

    assert response.result.confidence_score < 70
    assert response.result.needs_human_review is True