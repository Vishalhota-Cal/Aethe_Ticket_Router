"""
persistence/repository.py

Hides how data actually gets saved and fetched behind two simple
functions, save() and get_by_id(). Nothing outside this file should
import SQLAlchemy directly -- the orchestrator and API just call this.
"""

import json
from typing import List, Optional

from sqlalchemy.orm import joinedload

from ticket_router.domain.models import RoutingResult
from ticket_router.persistence.database import SessionLocal, engine
from ticket_router.persistence.models import AgentTraceRecord, Base, TicketRecord

Base.metadata.create_all(bind=engine)


class TicketRepository:
    """The only place in the codebase that talks to the database."""

    def save(
        self,
        ticket_id: str,
        correlation_id: str,
        subject: str,
        description: str,
        result: RoutingResult,
        trace: List[dict],
        embedding: Optional[List[float]] = None,
    ) -> None:
        session = SessionLocal()
        try:
            record = TicketRecord(
                id=ticket_id,
                correlation_id=correlation_id,
                subject=subject,
                description=description,
                category=result.category.value,
                priority=result.priority.value,
                assigned_team=result.assigned_team.value,
                reason=result.reason,
                confidence_score=result.confidence_score,
                needs_human_review=result.needs_human_review,
                sentiment=result.sentiment.value,
                embedding=json.dumps(embedding) if embedding is not None else None,
            )
            for step in trace:
                record.traces.append(
                    AgentTraceRecord(
                        agent_name=step["agent_name"],
                        duration_ms=step["duration_ms"],
                        success=step["success"],
                    )
                )
            session.merge(record)
            session.commit()
        finally:
            session.close()

    def get_by_id(self, ticket_id: str) -> Optional[TicketRecord]:
        session = SessionLocal()
        try:
            return (
                session.query(TicketRecord)
                .options(joinedload(TicketRecord.traces))
                .filter(TicketRecord.id == ticket_id)
                .first()
            )
        finally:
            session.close()

    def list_recent(self, limit: int = 200) -> List[TicketRecord]:
        """Every routed ticket, newest first -- backs the Past Tickets
        UI tab. Detached from the session before returning, so callers
        can read attributes after the session closes.
        """
        session = SessionLocal()
        try:
            records = (
                session.query(TicketRecord)
                .order_by(TicketRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            session.expunge_all()
            return records
        finally:
            session.close()

    def get_all_with_embeddings(self) -> List[TicketRecord]:
        """Every ticket that has a saved embedding -- the retrievable
        RAG knowledge base. Grows by one row every time a ticket is
        routed successfully.
        """
        session = SessionLocal()
        try:
            records = (
                session.query(TicketRecord)
                .filter(TicketRecord.embedding.isnot(None))
                .all()
            )
            session.expunge_all()
            return records
        finally:
            session.close()