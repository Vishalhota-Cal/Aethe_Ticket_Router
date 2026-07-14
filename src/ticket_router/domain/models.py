"""
domain/models.py

Defines the exact shape of data that flows through the whole system:
what a Ticket coming in looks like, what extra information agents carry
while working on it, and what the final RoutingResult handed back to
the caller looks like.
"""

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from ticket_router.domain.enums import Category, Priority, Sentiment, Team

# Attachments are stored as base64 text directly on the ticket row (see
# persistence/models.py) -- there's no separate blob store in this demo
# app. Capped well under typical request-body limits so a customer
# can't accidentally (or deliberately) submit something huge; ~5MB of
# real file data becomes ~6.7MB once base64-encoded (a 4/3 size
# expansion), so the base64 string itself is capped a little above
# that to leave headroom for encoding overhead.
MAX_ATTACHMENT_BASE64_CHARS = 7_000_000


class Ticket(BaseModel):
    """A support ticket exactly as it arrives from the outside world."""

    id: str
    # Empty subject/description is allowed through on purpose -- it's
    # treated the same as any other very-short/vague ticket (see
    # ReviewAgent's word-count rule), which handles it *meaningfully*
    # rather than needing a separate reject path. max_length is a cost/
    # abuse guard, not a content requirement: without it, one giant
    # paste could balloon LLM token cost or hit the provider's own
    # context-window limit unpredictably (mission criterion M4B2 --
    # very long input should be handled gracefully, not by accident).
    subject: str = Field(max_length=300)
    description: str = Field(max_length=5000)
    customer_tier: Optional[str] = None
    # Demo/test-only flag. When true, TriageAgent wraps the real LLM client
    # in a FlakyClient that deliberately fails its first couple of calls, so
    # orchestration/resilience.py's retry-with-backoff logic can be proven
    # live, on demand, instead of only being trusted from code review.
    simulate_failure: bool = False

    # --- Optional attachment (screenshot, short video, doc) a customer
    # can include with their ticket. All three stay None if nothing was
    # attached -- this is purely optional and never required to route a
    # ticket. attachment_data_base64 is the raw file bytes, base64-encoded
    # by the frontend before this request is ever made. ---
    attachment_filename: Optional[str] = None
    attachment_mime_type: Optional[str] = None
    attachment_data_base64: Optional[str] = None

    @model_validator(mode="after")
    def _validate_attachment(self) -> "Ticket":
        if self.attachment_data_base64 and len(self.attachment_data_base64) > MAX_ATTACHMENT_BASE64_CHARS:
            raise ValueError(
                "Attachment is too large -- please attach a file under roughly 5MB."
            )
        # An attachment is only meaningful as a complete set -- guard
        # against a filename with no data (or vice versa) reaching the
        # database in a half-saved state.
        has_any = any([self.attachment_filename, self.attachment_mime_type, self.attachment_data_base64])
        has_all = all([self.attachment_filename, self.attachment_mime_type, self.attachment_data_base64])
        if has_any and not has_all:
            raise ValueError(
                "Attachment filename, MIME type, and data must all be provided together, or not at all."
            )
        return self


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