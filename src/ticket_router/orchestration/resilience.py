"""
orchestration/resilience.py

A small retry-with-backoff wrapper for calls that might fail for
transient reasons (a network blip, a rate limit) -- distinct from
validation_agent.py's repair loop, which retries because the *content*
of the AI's answer was wrong, not because the network call itself
failed.
"""

import asyncio
from typing import Awaitable, Callable, List, Optional, TypeVar

from ticket_router.domain.exceptions import LLMProviderError
from ticket_router.domain.models import RetryAttempt

T = TypeVar("T")

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 1.0


async def call_with_retry(
    func: Callable[[], Awaitable[T]],
    log: Optional[List[RetryAttempt]] = None,
    agent_name: str = "LLM",
) -> T:
    """Call `func` (a zero-argument async function), retrying with
    exponential backoff if it raises LLMProviderError. Re-raises the
    last error if every attempt fails.

    If `log` is given, every attempt (success or failure) is appended to
    it as a RetryAttempt -- this is what lets the UI show, live, exactly
    what went wrong on earlier attempts before a retry succeeded.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = await func()
            if log is not None:
                log.append(RetryAttempt(agent_name=agent_name, attempt_number=attempt, success=True))
            return result
        except LLMProviderError as error:
            last_error = error
            if log is not None:
                log.append(
                    RetryAttempt(
                        agent_name=agent_name,
                        attempt_number=attempt,
                        success=False,
                        error_message=str(error),
                    )
                )
            if attempt == MAX_ATTEMPTS:
                break
            await asyncio.sleep(BASE_DELAY_SECONDS * (2 ** (attempt - 1)))

    raise last_error