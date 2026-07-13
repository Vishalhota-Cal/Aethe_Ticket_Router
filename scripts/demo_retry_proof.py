"""
scripts/demo_retry_proof.py

Standalone, runnable proof that orchestration/resilience.py's retry +
exponential backoff actually fires against a real induced failure --
not just a pytest assertion, but something you can run and watch happen
live in the terminal. Good to run in front of a mentor/SME as evidence.

Usage (from the project root):
    LLM_PROVIDER=mock DATABASE_URL="sqlite:///./demo_retry.db" \\
        PYTHONPATH=src python3 scripts/demo_retry_proof.py

Works with LLM_PROVIDER=openai too -- the forced failures happen before
the real API is ever called, so no extra API cost is wasted on the
failing attempts, only the one that finally succeeds.
"""

import asyncio
import time

from ticket_router.domain.models import Ticket
from ticket_router.observability.logging_config import configure_logging
from ticket_router.orchestration.orchestrator import TicketRoutingOrchestrator


async def main() -> None:
    configure_logging()

    ticket = Ticket(
        id="demo-retry-1",
        subject="Testing retry logic live",
        description="This ticket deliberately triggers simulated LLM failures to prove resilience.py works.",
        simulate_failure=True,
    )

    print("=" * 70)
    print("SUBMITTING TICKET WITH simulate_failure=True")
    print("Expect: 2 forced failures, real backoff delays, then a real success.")
    print("=" * 70)

    orchestrator = TicketRoutingOrchestrator()
    start = time.perf_counter()
    response = await orchestrator.route(ticket=ticket, correlation_id="demo-retry")
    total_seconds = time.perf_counter() - start

    print("\n--- RETRY LOG (what actually happened, attempt by attempt) ---")
    for entry in response.retry_log:
        status = "SUCCESS" if entry.success else "FAILED "
        detail = entry.error_message or "returned a usable response"
        print(f"  [{status}] {entry.agent_name} -- attempt {entry.attempt_number}: {detail}")

    print(f"\nTotal wall-clock time: {total_seconds:.2f}s "
          f"(expect ~3s: 1s backoff after attempt 1, 2s backoff after attempt 2)")

    print("\n--- FINAL RESULT (proves the request still succeeded despite the failures) ---")
    print(f"  category:           {response.result.category.value}")
    print(f"  priority:           {response.result.priority.value}")
    print(f"  assigned_team:      {response.result.assigned_team.value}")
    print(f"  sentiment:          {response.result.sentiment.value}")
    print(f"  confidence_score:   {response.result.confidence_score}")
    print(f"  needs_human_review: {response.result.needs_human_review}")

    failures = [e for e in response.retry_log if not e.success]
    successes = [e for e in response.retry_log if e.success]
    assert len(failures) == 2, "expected exactly 2 forced failures"
    assert len(successes) >= 1, "expected at least 1 eventual success"
    print("\nPASS: retry/backoff logic recovered from 2 real induced failures.")


if __name__ == "__main__":
    asyncio.run(main())