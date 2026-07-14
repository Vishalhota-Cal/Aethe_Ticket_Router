"""
api/routes/admin.py

The admin-side actions on an already-routed ticket: move it through its
lifecycle (New -> In Progress -> Resolved -> Closed), leave a
resolution comment, and -- if the AI got something wrong -- correct its
category, priority, or assigned team. These are human-in-the-loop
actions on top of the AI's own decision; they never overwrite what the
AI actually said, they're stored alongside it.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ticket_router.api.dependencies import get_repository
from ticket_router.domain.enums import Category, Priority, Team, TicketStatus
from ticket_router.persistence.repository import TicketRepository

router = APIRouter()


class AdminTicketUpdate(BaseModel):
    """The full admin management form for one ticket. All fields are
    submitted together every time -- leaving an override field blank
    clears it back to "keep the AI's decision," rather than leaving it
    untouched, since the admin UI always sends its complete current
    state.
    """

    status: TicketStatus
    resolution_comment: Optional[str] = None
    admin_category: Optional[Category] = None
    admin_priority: Optional[Priority] = None
    admin_team: Optional[Team] = None
    assigned_employee_id: Optional[int] = None


@router.patch("/tickets/{ticket_id}/admin")
async def update_ticket_admin(
    ticket_id: str,
    update: AdminTicketUpdate,
    repository: TicketRepository = Depends(get_repository),
):
    record = repository.update_ticket_admin_fields(
        ticket_id=ticket_id,
        status=update.status.value,
        resolution_comment=update.resolution_comment,
        admin_category=update.admin_category.value if update.admin_category else None,
        admin_priority=update.admin_priority.value if update.admin_priority else None,
        admin_team=update.admin_team.value if update.admin_team else None,
        assigned_employee_id=update.assigned_employee_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    return {
        "id": record.id,
        "status": record.status,
        "resolution_comment": record.resolution_comment,
        "admin_category": record.admin_category,
        "admin_priority": record.admin_priority,
        "admin_team": record.admin_team,
        "assigned_employee_id": record.assigned_employee_id,
        "assigned_employee_name": record.assigned_employee.name if record.assigned_employee else None,
        "assigned_department_name": record.assigned_employee.department.name if record.assigned_employee else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }