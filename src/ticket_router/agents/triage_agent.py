"""
agents/triage_agent.py

The only agent that actually talks to an AI. Builds a prompt from the
ticket's text, sends it through whichever LLM client is configured,
and hands back the AI's raw (not yet validated) answer.
"""

from ticket_router.agents.base import AgentResult
from ticket_router.domain.models import TicketContext
from ticket_router.llm.factory import get_llm_client
from ticket_router.llm.flaky_client import FlakyClient
from ticket_router.orchestration.resilience import call_with_retry


class TriageAgent:
    """Asks the AI to classify, prioritize, and assign a ticket in one
    request, instead of three separate ones.
    """

    async def execute(self, context: TicketContext) -> AgentResult:
        ticket = context.ticket

        prompt = (
            "You are a support ticket triage assistant.\n"
            f"Subject: {ticket.subject}\n"
            f"Description: {ticket.description}\n"
            "Return JSON with these exact fields: category, priority, "
            "assigned_team, reason, confidence_score (an integer 0-100), "
            "sentiment.\n"
            "\n"
            "category must be one of: Technical, Billing, Account, Security, General.\n"
            "assigned_team must match the category: Technical -> IT Support, "
            "Billing -> Billing Team, Account -> Account Management, "
            "Security -> Security Team, General -> General Support. Only "
            "deviate from this mapping if the ticket gives a clear reason to.\n"
            "\n"
            "sentiment must be one of: Angry, Frustrated, Neutral, Positive. "
            "Default to Neutral for tickets that simply describe a problem "
            "factually, with no emotional language. Only use Frustrated if "
            "the ticket explicitly describes a repeated, ongoing, or "
            "unresolved problem (e.g. 'still waiting', 'third time', "
            "'again', 'no one has helped'). Only use Angry if the ticket "
            "contains hostile, insulting, or aggressive language -- e.g. "
            "words like 'ridiculous', 'unacceptable', 'furious', ALL CAPS "
            "shouting, or multiple exclamation marks. Use Positive only if "
            "the ticket expresses thanks or satisfaction. Do not default to "
            "Frustrated just because a ticket describes a problem.\n"
            "\n"
            "If the ticket is very short, vague, or could reasonably belong "
            "to more than one category, reflect that uncertainty with a "
            "lower confidence_score instead of guessing confidently."
        )

        if context.retrieved_context:
            reference_lines = "\n".join(
                f"- \"{item.subject}\" was routed as category={item.category}, "
                f"priority={item.priority}, team={item.assigned_team} "
                f"(similarity {item.similarity_score})"
                for item in context.retrieved_context
            )
            prompt += (
                "\n\nFor reference, here are similar past tickets and how they "
                f"were actually routed:\n{reference_lines}\n"
                "Use these only as soft guidance for consistency with past "
                "decisions -- still judge this ticket on its own facts, and "
                "deviate if this ticket's details clearly differ."
            )

        llm = get_llm_client()
        if ticket.simulate_failure:
            # Demo-only: force the first 2 calls to fail so the retry/
            # backoff logic in resilience.py has something real to
            # recover from, instead of always succeeding on the first try.
            llm = FlakyClient(llm, fail_first_n=2)

        raw_response = await call_with_retry(
            lambda: llm.complete(prompt),
            log=context.retry_log,
            agent_name="TriageAgent",
        )

        return AgentResult(success=True, data=raw_response, agent_name="TriageAgent")