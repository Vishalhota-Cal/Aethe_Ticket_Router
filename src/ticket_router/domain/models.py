"""
domain/models.py

Defines the exact shape of data that flows through the whole system:
what a Ticket coming in looks like, what extra information agents carry
while working on it, and what the final RoutingResult handed back to
the caller looks like.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from ticket_router.domain.enums import Category, Priority, Sentiment, Team


class Ticket(BaseModel):
    """A support ticket exactly as it arrives from the outside world."""

    id: str
    subject: str
    description: str
    customer_tier: Optional[str] = None
    # Demo/test-only flag. When true, TriageAgent wraps the real LLM client
    # in a FlakyClient that deliberately fails its first couple of calls, so
    # orchestration/resilience.py's retry-with-backoff logic can be proven
    # live, on demand, instead of only being trusted from code review.
    simulate_failure: bool = False


class RoutingResult(BaseModel):
    """The final, validated decision returned to whoever submitted the
    ticket -- the exact shape described in the project brief.
    """

    category: Category
    priority: Priority
    assigned_team: Team
    reason: str
    confidence_score: int = Field(ge=0, le=100)
    needs_human_review: bool
    sentiment: Sentiment = Sentiment.NEUTRAL


class RetrievedTicket(BaseModel):
    """One past ticket pulled back by the RAG retrieval step -- shown as
    soft reference context to the triage prompt, and to the UI so the
    similarity search itself is visible, not a hidden implementation
    detail.
    """

    ticket_id: str
    subject: str
    category: str
    priority: str
    assigned_team: str
    similarity_score: float


class RetryAttempt(BaseModel):
    """One attempt at something that can transiently fail or come back
    invalid -- an LLM call timing out, or the AI's JSON failing schema
    validation. Logged regardless of whether the attempt succeeded, so
    the full retry/repair history of a request can be shown, not just
    its final outcome.
    """

    agent_name: str
    attempt_number: int
    success: bool
    error_message: Optional[str] = None


class TicketContext(BaseModel):
    """Everything the agents need while working on one ticket, plus a
    running record of what's happened to it so far.
    """

    ticket: Ticket
    correlation_id: str
    repair_attempts: int = 0
    raw_ai_response: Optional[str] = None
    draft_result: Optional[RoutingResult] = None
    retry_log: List[RetryAttempt] = Field(default_factory=list)
    # Populated by RetrievalAgent: the current ticket's own embedding
    # (saved after routing so the knowledge base keeps growing) and the
    # similar past tickets found for it (used as soft guidance context).
    ticket_embedding: Optional[List[float]] = None
    retrieved_context: List[RetrievedTicket] = Field(default_factory=list)


class TraceStep(BaseModel):
    """One agent's execution record: which agent ran, how long it took,
    and whether it succeeded. Purely for observability -- never used
    for routing decisions themselves.
    """

    agent_name: str
    duration_ms: float
    success: bool


class RoutingResponse(BaseModel):
    """What the API actually returns: the final decision, plus the full
    step-by-step trace of how it was reached, plus a log of every
    retry/repair attempt made along the way (empty on a clean run).
    """

    result: RoutingResult
    trace: List[TraceStep]
    retry_log: List[RetryAttempt] = Field(default_factory=list)
    retrieved_context: List[RetrievedTicket] = Field(default_factory=list)