"""
api/dependencies.py

Supplies ready-made objects (the orchestrator, the repository) to
route functions, instead of each route function building its own.
FastAPI calls these functions automatically whenever a route asks.
"""

import uuid

from ticket_router.orchestration.orchestrator import TicketRoutingOrchestrator
from ticket_router.persistence.repository import TicketRepository

_orchestrator = TicketRoutingOrchestrator()
_repository = TicketRepository()


def get_orchestrator() -> TicketRoutingOrchestrator:
    """Hand back the one shared orchestrator instance."""
    return _orchestrator


def get_repository() -> TicketRepository:
    """Hand back the one shared repository instance."""
    return _repository


def new_correlation_id() -> str:
    """Generate a fresh, unique ID to track one ticket's whole journey."""
    return str(uuid.uuid4())