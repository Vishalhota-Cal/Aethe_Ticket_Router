"""
tests/unit/orchestration/test_resilience_live.py

Proves the retry/backoff logic in orchestration/resilience.py actually
fires against a real induced failure, end to end through the real
orchestrator -- not just reviewed as correct-looking code. Uses
Ticket.simulate_failure, which wraps the LLM client in a FlakyClient
that deliberately fails its first 2 calls before succeeding.
"""

from ticket_router.domain.models import Ticket
from ticket_router.orchestration.orchestrator import TicketRoutingOrchestrator


async def test_simulated_failure_is_retried_and_eventually_succeeds():
    orchestrator = TicketRoutingOrchestrator()
    ticket = Ticket(
        id="chaos-1",
        subject="Testing retry logic",
        description="This ticket deliberately triggers simulated LLM failures.",
        simulate_failure=True,
    )

    response = await orchestrator.route(ticket=ticket, correlation_id="chaos-test")

    # The final result should still come back normal and valid -- proving
    # the retry recovered, rather than the request just failing outright.
    assert response.result is not None

    triage_entries = [e for e in response.retry_log if e.agent_name == "TriageAgent"]
    failures = [e for e in triage_entries if not e.success]
    successes = [e for e in triage_entries if e.success]

    assert len(failures) == 2
    assert len(successes) == 1
    assert "Simulated transient failure" in failures[0].error_message
    assert "Simulated transient failure" in failures[1].error_message