"""
api/routes/tickets.py

The actual HTTP endpoints for routing a ticket and looking one up
later. Translates HTTP requests into orchestrator/repository calls,
and results back into JSON.
"""

import base64
import binascii
import re

from fastapi import APIRouter, Depends, HTTPException, Response

from ticket_router.api.dependencies import get_orchestrator, get_repository, new_correlation_id
from ticket_router.domain.models import RoutingResponse, Ticket
from ticket_router.orchestration.orchestrator import TicketRoutingOrchestrator
from ticket_router.persistence.repository import TicketRepository

router = APIRouter()

# Filenames come straight from whatever the customer's browser sent when
# they picked a file -- never trust that as safe to drop directly into an
# HTTP header. Strip anything that isn't a plain, printable filename
# character before it ever reaches Content-Disposition, so a filename
# containing a quote or a CR/LF can't break or inject into the header.
_UNSAFE_FILENAME_CHARS = re.compile(r'[\r\n"\\/]')


def _safe_attachment_filename(filename: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", filename).strip()
    return cleaned or "attachment"


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
            "status": record.status,
            "resolution_comment": record.resolution_comment,
            "admin_category": record.admin_category,
            "admin_priority": record.admin_priority,
            "admin_team": record.admin_team,
            "assigned_employee_id": record.assigned_employee_id,
            "assigned_employee_name": record.assigned_employee.name if record.assigned_employee else None,
            "assigned_department_name": record.assigned_employee.department.name if record.assigned_employee else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            # Metadata only -- the actual attachment bytes are fetched
            # separately via GET /tickets/{id}/attachment, so listing
            # tickets stays fast regardless of attachment size/count.
            "attachment_filename": record.attachment_filename,
            "attachment_mime_type": record.attachment_mime_type,
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
        "status": record.status,
        "resolution_comment": record.resolution_comment,
        "admin_category": record.admin_category,
        "admin_priority": record.admin_priority,
        "admin_team": record.admin_team,
        "assigned_employee_id": record.assigned_employee_id,
        "assigned_employee_name": record.assigned_employee.name if record.assigned_employee else None,
        "assigned_department_name": record.assigned_employee.department.name if record.assigned_employee else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "attachment_filename": record.attachment_filename,
        "attachment_mime_type": record.attachment_mime_type,
        "trace": [
            {"agent_name": t.agent_name, "duration_ms": t.duration_ms, "success": t.success}
            for t in record.traces
        ],
    }


@router.get("/tickets/{ticket_id}/attachment")
async def get_ticket_attachment(
    ticket_id: str,
    repository: TicketRepository = Depends(get_repository),
):
    """Serves the raw attachment bytes (decoded from the base64 stored
    on the row) with the original content type and an inline
    Content-Disposition, so a browser tab opened on this URL displays
    an image/PDF/video directly rather than forcing a download -- other
    file types the browser can't render still just download, which is
    the normal browser behavior for "inline" content it doesn't know
    how to show.
    """
    record = repository.get_by_id(ticket_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if not record.attachment_data:
        raise HTTPException(status_code=404, detail="This ticket has no attachment")

    try:
        raw_bytes = base64.b64decode(record.attachment_data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=500, detail="Stored attachment data is corrupted")

    filename = _safe_attachment_filename(record.attachment_filename or "attachment")
    return Response(
        content=raw_bytes,
        media_type=record.attachment_mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )