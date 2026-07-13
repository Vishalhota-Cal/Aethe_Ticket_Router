"""
tests/unit/agents/test_review_agent.py

Unit tests for ReviewAgent's deterministic rules -- no AI call
involved, so these run instantly and need no mock at all.
"""

import pytest

from ticket_router.agents.review_agent import ReviewAgent
from ticket_router.domain.enums import Category, Priority, Sentiment, Team
from ticket_router.domain.models import RoutingResult, Ticket, TicketContext


def make_context(
    confidence: int,
    category: Category,
    repair_attempts: int = 0,
    sentiment: Sentiment = Sentiment.NEUTRAL,
    subject: str = "Cannot access dashboard reports",
    description: str = "The reports page has been throwing errors since this morning.",
) -> TicketContext:
    ticket = Ticket(id="1", subject=subject, description=description)
    context = TicketContext(ticket=ticket, correlation_id="test-id", repair_attempts=repair_attempts)
    context.draft_result = RoutingResult(
        category=category,
        priority=Priority.HIGH,
        assigned_team=Team.IT_SUPPORT,
        reason="test reason",
        confidence_score=confidence,
        needs_human_review=False,
        sentiment=sentiment,
    )
    return context


async def test_high_confidence_non_security_no_repairs_does_not_need_review():
    context = make_context(confidence=95, category=Category.TECHNICAL)
    result = await ReviewAgent().execute(context)
    assert result.data.needs_human_review is False


async def test_low_confidence_needs_review():
    context = make_context(confidence=50, category=Category.TECHNICAL)
    result = await ReviewAgent().execute(context)
    assert result.data.needs_human_review is True


async def test_security_category_always_needs_review():
    context = make_context(confidence=99, category=Category.SECURITY)
    result = await ReviewAgent().execute(context)
    assert result.data.needs_human_review is True


async def test_any_repair_attempt_forces_review():
    context = make_context(confidence=99, category=Category.TECHNICAL, repair_attempts=1)
    result = await ReviewAgent().execute(context)
    assert result.data.needs_human_review is True


async def test_angry_sentiment_forces_review_even_at_high_confidence():
    context = make_context(confidence=95, category=Category.GENERAL, sentiment=Sentiment.ANGRY)
    result = await ReviewAgent().execute(context)
    assert result.data.needs_human_review is True


async def test_very_short_ticket_forces_review_even_at_high_confidence():
    # Mirrors the real "Help" / "Broken." edge case: the AI can still return
    # high confidence on a vague ticket, so this must be caught by the
    # deterministic word-count rule, not by trusting confidence_score.
    context = make_context(confidence=95, category=Category.TECHNICAL, subject="Help", description="Broken.")
    result = await ReviewAgent().execute(context)
    assert result.data.needs_human_review is True