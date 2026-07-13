"""
agents/validation_agent.py

Turns the AI's raw text into a trustworthy RoutingResult. If the text
doesn't parse as JSON or doesn't satisfy the RoutingResult schema, asks
the AI to fix its own answer, up to a fixed number of times, before
giving up.
"""

import json

from pydantic import ValidationError

from ticket_router.agents.base import AgentResult
from ticket_router.domain.exceptions import ValidationFailedError
from ticket_router.domain.models import RetryAttempt, RoutingResult, TicketContext
from ticket_router.llm.factory import get_llm_client
from ticket_router.orchestration.resilience import call_with_retry

MAX_REPAIR_ATTEMPTS = 2


class ValidationAgent:
    """Validates the AI's output, repairing it through re-prompting when
    needed, and never allowing bad data further into the system.
    """

    async def execute(self, context: TicketContext) -> AgentResult:
        raw_response = context.raw_ai_response
        parse_attempt = 0

        while True:
            parse_attempt += 1
            try:
                parsed = json.loads(raw_response)
                result = RoutingResult(
                    category=parsed["category"],
                    priority=parsed["priority"],
                    assigned_team=parsed["assigned_team"],
                    reason=parsed["reason"],
                    confidence_score=parsed["confidence_score"],
                    needs_human_review=False,
                    sentiment=parsed.get("sentiment", "Neutral"),
                )
                context.retry_log.append(
                    RetryAttempt(agent_name="ValidationAgent", attempt_number=parse_attempt, success=True)
                )
                return AgentResult(success=True, data=result, agent_name="ValidationAgent")

            except (json.JSONDecodeError, ValidationError, KeyError) as error:
                # This is a *content* anomaly (the AI's answer didn't match
                # the schema), logged separately from the transport-level
                # retry entries call_with_retry adds below -- so the UI can
                # show exactly what was wrong with the first attempt.
                context.retry_log.append(
                    RetryAttempt(
                        agent_name="ValidationAgent",
                        attempt_number=parse_attempt,
                        success=False,
                        error_message=f"AI response failed schema check: {error}",
                    )
                )

                if context.repair_attempts >= MAX_REPAIR_ATTEMPTS:
                    raise ValidationFailedError(
                        f"AI output still invalid after {context.repair_attempts} "
                        f"repair attempts: {error}",
                        attempts=context.repair_attempts,
                    )

                context.repair_attempts += 1
                llm = get_llm_client()
                repair_prompt = (
                    "Your previous answer was:\n"
                    f"{raw_response}\n"
                    f"It failed with this error: {error}\n"
                    "Please resend corrected JSON with the exact same fields."
                )
                raw_response = await call_with_retry(
                    lambda: llm.complete(repair_prompt),
                    log=context.retry_log,
                    agent_name="ValidationAgent (repair call)",
                )