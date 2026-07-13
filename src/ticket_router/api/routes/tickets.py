"""
api/routes/tickets.py

The actual HTTP endpoints for routing a ticket and looking one up
later. Translates HTTP requests into orchestrator/repository calls,
and results back into JSON.
"""

from fastapi import APIRouter, Depends, HTTPException

from ticket_router.api.dependencies import get_orchestrator, get_repository, new_correlation_id
from ticket_router.domain.models import RoutingResponse, Ticket
from ticket_router.orchestration.orchestrator import TicketRoutingOrchestrator
from ticket_router.persistence.repository import TicketRepository

router = APIRouter()


@router.post("/tickets/route", response_model=RoutingResponse)
async def route_ticket(
    ticket: Ticket,
    orchestrator: TicketRoutingOrchestrator = Depends(get_orchestrator),
) -> RoutingResponse:
    correlation_id = new_correlation_id()
    return await orchestrator.route(ticket=ticket, correlation_id=correlation_id)


@router.get("/tickets")
async def list_tickets(
    limit: int = 200,
    repository: TicketRepository = Depends(get_repository),
):
    """Every routed ticket, newest first -- backs the Past Tickets tab."""
    records = repository.list_recent(limit=limit)
    return [
        {
            "id": record.id,
            "subject": record.subject,
            "description": record.description,
            "category": record.category,
            "priority": record.priority,
            "assigned_team": record.assigned_team,
            "sentiment": record.sentiment,
            "confidence_score": record.confidence_score,
            "needs_human_review": record.needs_human_review,
            "created_at": record.created_at.isoformat(),
        }
        for record in records
    ]


@router.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    repository: TicketRepository = Depends(get_repository),
):
    record = repository.get_by_id(ticket_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return {
        "id": record.id,
        "correlation_id": record.correlation_id,
        "subject": record.subject,
        "description": record.description,
        "category": record.category,
        "priority": record.priority,
        "assigned_team": record.assigned_team,
        "reason": record.reason,
        "sentiment": record.sentiment,
        "confidence_score": record.confidence_score,
        "needs_human_review": record.needs_human_review,
        "created_at": record.created_at.isoformat(),
        "trace": [
            {"agent_name": t.agent_name, "duration_ms": t.duration_ms, "success": t.success}
            for t in record.traces
        ],
    }