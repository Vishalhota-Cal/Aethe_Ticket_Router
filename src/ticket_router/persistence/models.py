"""
persistence/models.py

The actual database table definitions -- separate from
domain/models.py, since "what's saved to disk" is allowed to evolve
independently from "what's passed around in memory."
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class TicketRecord(Base):
    """One row per routed ticket -- the final decision, saved."""

    __tablename__ = "tickets"

    id = Column(String, primary_key=True)
    correlation_id = Column(String, index=True)
    subject = Column(String)
    description = Column(String)
    category = Column(String)
    priority = Column(String)
    assigned_team = Column(String)
    reason = Column(String)
    confidence_score = Column(Integer)
    needs_human_review = Column(Boolean)
    sentiment = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # JSON-encoded embedding vector for this ticket's text -- populated
    # after routing so the RAG knowledge base grows with every ticket
    # the system handles. Nullable because older rows (or rows saved
    # while the embeddings call failed) simply won't be retrievable yet.
    embedding = Column(String, nullable=True)

    traces = relationship("AgentTraceRecord", back_populates="ticket")


class AgentTraceRecord(Base):
    """One row per agent execution -- which agent ran, how long it
    took, and whether it succeeded, for one specific ticket.
    """

    __tablename__ = "agent_traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, ForeignKey("tickets.id"))
    agent_name = Column(String)
    duration_ms = Column(Float)
    success = Column(Boolean)

    ticket = relationship("TicketRecord", back_populates="traces")