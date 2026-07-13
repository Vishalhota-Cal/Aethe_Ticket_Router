"""
agents/review_agent.py

Decides the final needs_human_review value using fixed, deterministic
rules -- no AI call. This keeps the human-escalation decision fully
auditable: every outcome can be traced back to a specific rule.
"""

from ticket_router.agents.base import AgentResult
from ticket_router.domain.models import TicketContext

CONFIDENCE_THRESHOLD = 70
ALWAYS_REVIEW_CATEGORIES = {"Security"}
ALWAYS_REVIEW_SENTIMENTS = {"Angry", "Frustrated"}

# A ticket this short gives the AI almost nothing to work with (e.g. "Help" /
# "Broken."). The AI's own confidence_score is not reliable enough on its own
# to catch this -- it can still report high confidence on a vague ticket --
# so this is enforced as a deterministic, word-count-based rule instead,
# independent of whatever confidence the AI happens to return.
SHORT_TICKET_WORD_THRESHOLD = 6


class ReviewAgent:
    """Applies fixed business rules on top of a validated draft result."""

    async def execute(self, context: TicketContext) -> AgentResult:
        draft = context.draft_result
        needs_review = False

        if draft.confidence_score < CONFIDENCE_THRESHOLD:
            needs_review = True

        if draft.category.value in ALWAYS_REVIEW_CATEGORIES:
            needs_review = True

        if context.repair_attempts > 0:
            needs_review = True

        if draft.sentiment.value in ALWAYS_REVIEW_SENTIMENTS:
            needs_review = True

        ticket = context.ticket
        combined_text = f"{ticket.subject} {ticket.description}"
        word_count = len(combined_text.split())
        if word_count <= SHORT_TICKET_WORD_THRESHOLD:
            needs_review = True

        draft.needs_human_review = needs_review

        return AgentResult(success=True, data=draft, agent_name="ReviewAgent")