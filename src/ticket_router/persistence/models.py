"""
persistence/models.py

The actual database table definitions -- separate from
domain/models.py, since "what's saved to disk" is allowed to evolve
independently from "what's passed around in memory."
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
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

    # --- Admin / lifecycle fields -- set by a human working the ticket
    # after routing, completely separate from the AI's own decision
    # above. The AI's category/priority/assigned_team columns are never
    # overwritten; an admin correction is stored alongside them instead,
    # so both "what the AI said" and "what a human corrected it to" stay
    # visible and auditable. ---
    # Indexed -- this column is filtered/grouped-by constantly (the
    # Jira-style board buckets every ticket into a column by this value,
    # and auto-assignment counts each employee's open tickets by it).
    status = Column(String, nullable=False, default="New", index=True)
    resolution_comment = Column(String, nullable=True)
    admin_category = Column(String, nullable=True)
    admin_priority = Column(String, nullable=True)
    admin_team = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Which real person is working this ticket -- separate from
    # assigned_team (the AI's queue/routing decision). Nullable: most
    # tickets sit unassigned until an admin picks someone.
    assigned_employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    assigned_employee = relationship("Employee")

    # --- Optional customer-provided attachment (screenshot, video, doc)
    # -- entirely optional, all three stay NULL if nothing was attached.
    # Stored as base64 text directly in the row rather than on a
    # separate blob store or filesystem path, since this is a
    # single-SQLite-file demo app; attachment_data is served back out
    # (decoded) through a dedicated endpoint rather than ever being
    # included in a ticket list response, so listing tickets stays fast
    # and light regardless of how many/how large the attachments are. ---
    attachment_filename = Column(String, nullable=True)
    attachment_mime_type = Column(String, nullable=True)
    attachment_data = Column(Text, nullable=True)

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


class Department(Base):
    """A real-world department, e.g. IT, Finance, Security, HR, Admin --
    the org structure that employees belong to. Separate from Team
    (assigned_team on TicketRecord), which is the AI's routing/queue
    decision, not an org chart.
    """

    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)

    employees = relationship("Employee", back_populates="department")


class Employee(Base):
    """A real person who can be assigned a ticket to work. Belongs to
    exactly one department.
    """

    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    role = Column(String, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)

    department = relationship("Department", back_populates="employees")