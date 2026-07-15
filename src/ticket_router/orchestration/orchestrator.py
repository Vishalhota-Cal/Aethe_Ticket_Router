"""
orchestration/orchestrator.py

The conductor. Calls TriageAgent, ValidationAgent, and ReviewAgent in
order, passes data between them through the shared TicketContext,
times and logs every step, saves the result and trace, and builds a
safe fallback if validation fails beyond recovery.
"""

import time
from typing import List

from ticket_router.agents.retrieval_agent import RetrievalAgent
from ticket_router.agents.review_agent import ReviewAgent
from ticket_router.agents.triage_agent import TriageAgent
from ticket_router.agents.validation_agent import ValidationAgent
from ticket_router.domain.enums import Category, Priority, Team
from ticket_router.domain.exceptions import ValidationFailedError
from ticket_router.domain.models import (
    RoutingResponse,
    RoutingResult,
    Ticket,
    TicketContext,
    TraceStep,
)
from ticket_router.observability.logging_config import get_logger
from ticket_router.persistence.repository import TicketRepository

logger = get_logger(__name__)


class TicketRoutingOrchestrator:
    """Coordinates the full journey of a single ticket from raw input to
    a final, validated RoutingResult -- with timing, logging, and
    persistence wrapped around every step.
    """

    def __init__(self) -> None:
        self.repository = TicketRepository()
        self.retrieval_agent = RetrievalAgent(self.repository)
        self.triage_agent = TriageAgent()
        self.validation_agent = ValidationAgent()
        self.review_agent = ReviewAgent()

    @staticmethod
    def _safe_fallback_result(reason: str) -> RoutingResult:
        """The one safe, always-valid result this system falls back to
        whenever it can't produce a real AI decision -- whether that's
        because the AI's output never became valid JSON (see
        ValidationFailedError below) or because the AI provider itself
        is unreachable (bad key, network outage, rate limit). Either
        way: never crash, never leave the ticket unrouted, always flag
        it for a human instead of guessing.
        """
        return RoutingResult(
            category=Category.GENERAL,
            priority=Priority.MEDIUM,
            assigned_team=Team.GENERAL_SUPPORT,
            reason=reason,
            confidence_score=0,
            needs_human_review=True,
        )

    def _save_fallback(
        self,
        ticket: Ticket,
        correlation_id: str,
        trace: List[TraceStep],
        context: TicketContext,
        fallback: RoutingResult,
    ) -> RoutingResponse:
        self.repository.save(
            ticket_id=ticket.id,
            correlation_id=correlation_id,
            subject=ticket.subject,
            description=ticket.description,
            result=fallback,
            trace=[step.model_dump() for step in trace],
            embedding=context.ticket_embedding,
            attachment_filename=ticket.attachment_filename,
            attachment_mime_type=ticket.attachment_mime_type,
            attachment_data=ticket.attachment_data_base64,
            customer_name=ticket.customer_name,
            customer_email=ticket.customer_email,
        )
        return RoutingResponse(
            result=fallback,
            trace=trace,
            retry_log=context.retry_log,
            retrieved_context=context.retrieved_context,
        )

    async def route(self, ticket: Ticket, correlation_id: str) -> RoutingResponse:
        context = TicketContext(ticket=ticket, correlation_id=correlation_id)
        trace: List[TraceStep] = []

        def record(agent_name: str, start: float, success: bool) -> None:
            duration_ms = (time.perf_counter() - start) * 1000
            trace.append(TraceStep(agent_name=agent_name, duration_ms=duration_ms, success=success))
            logger.info(
                "[%s] %s finished in %.1fms (success=%s)",
                correlation_id, agent_name, duration_ms, success,
            )

        logger.info("[%s] Routing ticket %s", correlation_id, ticket.id)

        # RAG is an enhancement, not a hard dependency -- if the
        # embeddings call fails for any reason (bad key, rate limit,
        # network blip), routing still proceeds without similar-ticket
        # context rather than failing the whole request.
        start = time.perf_counter()
        try:
            await self.retrieval_agent.execute(context)
            record("RetrievalAgent", start, True)
        except Exception as error:
            record("RetrievalAgent", start, False)
            logger.warning(
                "[%s] RetrievalAgent failed, continuing without similar-ticket context: %s",
                correlation_id, error,
            )

        # TriageAgent is the one step with a hard external dependency (a
        # real LLM call). call_with_retry inside it already retries
        # transient failures with backoff, and openai_client.py wraps
        # every request-time failure as LLMProviderError -- but a bad
        # API key or broken network can also surface as something else
        # entirely (e.g. the provider SDK failing while *constructing*
        # its client, before a request is even attempted). Rather than
        # trust that every failure mode is perfectly wrapped, this
        # catches broadly here, the same way the RetrievalAgent call
        # above does: from the caller's perspective, "the AI is
        # unreachable" should always degrade to the same safe,
        # human-flagged fallback a validation failure gets below --
        # never an unhandled 500, no matter *how* the AI provider failed.
        start = time.perf_counter()
        try:
            triage_result = await self.triage_agent.execute(context)
            record("TriageAgent", start, triage_result.success)
            context.raw_ai_response = triage_result.data
        except Exception as error:
            record("TriageAgent", start, False)
            logger.warning(
                "[%s] TriageAgent failed -- AI provider unavailable (%s): %s",
                correlation_id, type(error).__name__, error,
            )
            fallback = self._safe_fallback_result(
                "AI provider is currently unavailable (connection, authentication, "
                "or rate-limit failure); this ticket needs manual triage."
            )
            return self._save_fallback(ticket, correlation_id, trace, context, fallback)

        start = time.perf_counter()
        try:
            validation_result = await self.validation_agent.execute(context)
            record("ValidationAgent", start, True)
        except ValidationFailedError as error:
            record("ValidationAgent", start, False)
            logger.warning("[%s] Validation failed permanently: %s", correlation_id, error)

            fallback = self._safe_fallback_result(
                "Automated routing failed after repair attempts; needs manual triage."
            )
            return self._save_fallback(ticket, correlation_id, trace, context, fallback)

        context.draft_result = validation_result.data

        start = time.perf_counter()
        review_result = await self.review_agent.execute(context)
        record("ReviewAgent", start, review_result.success)

        final_result = review_result.data

        self.repository.save(
            ticket_id=ticket.id,
            correlation_id=correlation_id,
            subject=ticket.subject,
            description=ticket.description,
            result=final_result,
            trace=[step.model_dump() for step in trace],
            embedding=context.ticket_embedding,
            attachment_filename=ticket.attachment_filename,
            attachment_mime_type=ticket.attachment_mime_type,
            attachment_data=ticket.attachment_data_base64,
            customer_name=ticket.customer_name,
            customer_email=ticket.customer_email,
        )

        logger.info(
            "[%s] Done: %s/%s, needs_human_review=%s",
            correlation_id, final_result.category.value, final_result.priority.value,
            final_result.needs_human_review,
        )

        return RoutingResponse(
            result=final_result,
            trace=trace,
            retry_log=context.retry_log,
            retrieved_context=context.retrieved_context,
        )