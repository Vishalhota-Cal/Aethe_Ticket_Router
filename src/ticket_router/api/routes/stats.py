"""
api/routes/stats.py

Lifetime (all-time) stats across every ticket this system has ever
routed. This backs the "Lifetime Impact" banner on the frontend, which
is the strongest evidence for the manual-vs-AI time comparison: it's
not one CSV batch, it's the system's whole history, growing every time
someone routes a ticket.
"""

from fastapi import APIRouter, Depends

from ticket_router.api.dependencies import get_repository
from ticket_router.persistence.repository import TicketRepository

router = APIRouter()


@router.get("/stats/time-savings")
async def time_savings(
    repository: TicketRepository = Depends(get_repository),
):
    """Total tickets ever routed + total real AI processing time.

    The manual-minutes-per-ticket assumption is deliberately NOT
    computed here -- it's user-editable on the frontend, so the
    frontend multiplies total_tickets_routed by whatever assumption
    the user has set, keeping "measured" (AI time) and "assumed"
    (manual time) clearly separate.
    """
    return repository.get_time_savings_stats()


@router.get("/stats/analytics")
async def analytics(
    repository: TicketRepository = Depends(get_repository),
):
    """Business-facing analytics for the Admin Console: department/
    category/priority volume, AI trustworthiness (confidence, review
    rate, admin-override rate), employee workload balance, sentiment
    mix, daily volume, and average resolution time. Purely descriptive
    aggregates -- see repository.get_analytics_summary() for details.
    """
    return repository.get_analytics_summary()