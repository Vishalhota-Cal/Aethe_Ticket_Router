"""
llm/flaky_client.py

A demo/test-only wrapper around a real LLMClient. It deliberately fails
the first N calls with LLMProviderError before letting requests through
normally. This exists so orchestration/resilience.py's retry-with-backoff
logic can be proven to actually fire against a real induced failure --
on demand, from the UI -- instead of only being trusted because the code
looks right.

Never used unless a request explicitly opts in via Ticket.simulate_failure.
"""

from ticket_router.domain.exceptions import LLMProviderError
from ticket_router.llm.client import LLMClient


class FlakyClient:
    """Wraps a real LLMClient and fails the first `fail_first_n` calls."""

    def __init__(self, real_client: LLMClient, fail_first_n: int = 2) -> None:
        self._real_client = real_client
        self._fail_first_n = fail_first_n
        self._call_count = 0

    async def complete(self, prompt: str) -> str:
        self._call_count += 1
        if self._call_count <= self._fail_first_n:
            raise LLMProviderError(
                f"Simulated transient failure (attempt {self._call_count} "
                f"of {self._fail_first_n} forced failures)"
            )
        return await self._real_client.complete(prompt)