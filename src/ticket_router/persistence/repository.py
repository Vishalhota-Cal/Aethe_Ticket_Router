"""
persistence/repository.py

Hides how data actually gets saved and fetched behind two simple
functions, save() and get_by_id(). Nothing outside this file should
import SQLAlchemy directly -- the orchestrator and API just call this.
"""

import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, inspect, text
from sqlalchemy.orm import joinedload

from ticket_router.domain.enums import TicketStatus
from ticket_router.domain.models import RoutingResult
from ticket_router.persistence.database import SessionLocal, engine
from ticket_router.persistence.models import (
    AgentTraceRecord,
    Base,
    Department,
    Employee,
    TicketRecord,
)

Base.metadata.create_all(bind=engine)


def _ensure_schema_is_current() -> None:
    """create_all() only creates tables that don't exist yet -- it never
    adds a column to a table that's already there. This project doesn't
    use a full migration tool (Alembic), and this schema has changed
    several times as features were added, each time requiring the
    database file to be deleted by hand. This fixes that permanently:
    it compares every table's real columns against what the models now
    expect, and ALTERs in whatever's missing (backfilling a sensible
    default for existing rows where one is defined). From now on, a
    schema change just works on the next restart -- no more deleting
    ticket_router.db.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            if table.name not in existing_tables:
                continue  # brand new table -- create_all() already built it correctly

            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue

                col_type = column.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))

                # If the model defines a plain (non-callable) default,
                # backfill it into existing rows so they don't just sit
                # at NULL for a column that's supposed to have one.
                default_value = None
                if column.default is not None and not callable(column.default.arg):
                    default_value = column.default.arg
                if default_value is not None:
                    conn.execute(
                        text(f'UPDATE "{table.name}" SET "{column.name}" = :val WHERE "{column.name}" IS NULL'),
                        {"val": default_value},
                    )

        # create_all() also only adds indexes when it creates a table for
        # the first time -- it won't retroactively index a column on a
        # table that already existed. status is now indexed on the model
        # (see persistence/models.py) since the Jira-style board and
        # auto-assignment both filter/count by it constantly; this makes
        # sure a database that predates that change gets the index too.
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tickets_status ON tickets (status)"))


_ensure_schema_is_current()


def _seed_default_departments_and_employees() -> None:
    """Makes sure a realistic, full company org chart of departments (and
    a couple of employees in each) exists -- checked one department at a
    time, so this is safe to run on every startup. If a default
    department already exists it's left completely untouched (no
    duplicate employees, no overwriting anything the user renamed or
    edited); only the ones still missing get created. That also means
    growing this list later doesn't require deleting the database --
    the newly added departments just appear on the next restart.
    """
    session = SessionLocal()
    try:
        defaults = {
            "IT": ["Ravi Shankar", "Meera Iyer"],
            "Finance": ["Ankit Verma"],
            "Security": ["Divya Reddy"],
            "HR": ["Sanjay Gupta"],
            "Admin": ["Neha Kapoor"],
            "General Support": ["Karthik Rao"],
            "Legal": ["Asha Menon"],
            "Sales": ["Rohan Malhotra"],
            "Marketing": ["Priya Nair"],
            "Operations": ["Vikram Desai"],
            "Engineering": ["Anjali Bhatt"],
            "Product": ["Rahul Chandran"],
            "Facilities": ["Suresh Pillai"],
            "Procurement": ["Kabir Chawla"],
            "Customer Success": ["Ishita Sharma"],
        }
        for dept_name, employee_names in defaults.items():
            existing = session.query(Department).filter(Department.name == dept_name).first()
            if existing is not None:
                continue  # already exists -- don't touch or duplicate it

            department = Department(name=dept_name)
            session.add(department)
            session.flush()  # populates department.id without a full commit
            for emp_name in employee_names:
                session.add(Employee(name=emp_name, department_id=department.id, role="Support Agent"))
        session.commit()
    finally:
        session.close()


_seed_default_departments_and_employees()


# Maps the AI's routing decision (Team) onto a real department in the
# directory, so auto-assignment has somewhere to look. This is
# intentionally a plain dict, not a shared enum -- Team is the AI's
# queue/routing decision, Department is the org chart, and keeping the
# mapping here (persistence layer) means it can be tuned without
# touching the AI pipeline at all.
TEAM_TO_DEPARTMENT = {
    "IT Support": "IT",
    "Billing Team": "Finance",
    "Security Team": "Security",
    "Account Management": "Customer Success",
    "General Support": "General Support",
}

# Used to sort tickets the way a Jira-style board would -- most urgent
# first within each status column. Unknown/missing priority values sort
# last (weight 0) rather than raising.
_PRIORITY_WEIGHT = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}


class TicketRepository:
    """The only place in the codebase that talks to the database."""

    def _auto_assign_employee(self, session, assigned_team: str) -> Optional[int]:
        """Picks the least-busy active employee in the department mapped
        from the AI's team decision, so a new ticket lands on someone's
        desk immediately instead of sitting unassigned until an admin
        manually picks someone. "Least-busy" = fewest tickets currently
        open (status New or In Progress). Ties broken by employee id for
        determinism (same inputs always produce the same assignment).

        Returns None -- leaving the ticket unassigned, safe for an admin
        to fill in by hand -- if the team has no mapped department, that
        department doesn't exist, or it has no active employees yet.
        """
        department_name = TEAM_TO_DEPARTMENT.get(assigned_team)
        if department_name is None:
            return None

        department = session.query(Department).filter(Department.name == department_name).first()
        if department is None:
            return None

        candidates = (
            session.query(Employee)
            .filter(Employee.department_id == department.id, Employee.active.is_(True))
            .order_by(Employee.id)
            .all()
        )
        if not candidates:
            return None

        open_statuses = ("New", "In Progress")
        best_employee = None
        best_open_count = None
        for employee in candidates:
            open_count = (
                session.query(func.count(TicketRecord.id))
                .filter(
                    TicketRecord.assigned_employee_id == employee.id,
                    TicketRecord.status.in_(open_statuses),
                )
                .scalar()
                or 0
            )
            if best_open_count is None or open_count < best_open_count:
                best_employee = employee
                best_open_count = open_count

        return best_employee.id if best_employee else None

    def save(
        self,
        ticket_id: str,
        correlation_id: str,
        subject: str,
        description: str,
        result: RoutingResult,
        trace: List[dict],
        embedding: Optional[List[float]] = None,
        attachment_filename: Optional[str] = None,
        attachment_mime_type: Optional[str] = None,
        attachment_data: Optional[str] = None,
    ) -> None:
        session = SessionLocal()
        try:
            # If this exact ticket_id was already saved and already has
            # an assignment (whether auto-picked or set by an admin),
            # keep it -- save() can in principle be called again for the
            # same id, and a re-save should never silently wipe out an
            # existing assignment or an admin's status change.
            existing = session.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
            if existing is not None and existing.assigned_employee_id is not None:
                assigned_employee_id = existing.assigned_employee_id
                initial_status = existing.status
            else:
                assigned_employee_id = self._auto_assign_employee(session, result.assigned_team.value)
                if existing is not None:
                    # Re-save of a ticket that still has no employee --
                    # preserve whatever status it already has rather
                    # than recomputing it.
                    initial_status = existing.status
                elif assigned_employee_id is not None:
                    # A brand new ticket that lands directly on
                    # someone's desk shouldn't sit in the "New" column
                    # -- it's already being worked, not just queued.
                    initial_status = TicketStatus.IN_PROGRESS.value
                else:
                    initial_status = TicketStatus.NEW.value

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
                assigned_employee_id=assigned_employee_id,
                status=initial_status,
                attachment_filename=attachment_filename,
                attachment_mime_type=attachment_mime_type,
                attachment_data=attachment_data,
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
                .options(
                    joinedload(TicketRecord.traces),
                    joinedload(TicketRecord.assigned_employee).joinedload(Employee.department),
                )
                .filter(TicketRecord.id == ticket_id)
                .first()
            )
        finally:
            session.close()

    def list_recent(self, limit: int = 200) -> List[TicketRecord]:
        """Every routed ticket -- backs the Past Tickets tab and the
        Admin Console's Jira-style board. Ordered highest-priority-first
        (Critical, High, Medium, Low), newest-first as the tiebreak
        within the same priority -- Python's sort is stable, so
        re-sorting the already-recency-ordered query result by priority
        alone preserves that recency ordering inside each priority
        group. That means each status column on the board is already in
        the right order without the frontend needing to re-sort it.
        Detached from the session before returning, so callers can read
        attributes after the session closes.
        """
        session = SessionLocal()
        try:
            records = (
                session.query(TicketRecord)
                .options(joinedload(TicketRecord.assigned_employee).joinedload(Employee.department))
                .order_by(TicketRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            session.expunge_all()
            records.sort(key=lambda r: -_PRIORITY_WEIGHT.get(r.priority, 0))
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

    def get_time_savings_stats(self) -> dict:
        """Lifetime totals across every ticket this system has ever
        routed -- not just the tickets in one CSV batch. Backs the
        "Lifetime Impact" banner, which is the strongest evidence for
        the manual-vs-AI time comparison: it shows the savings add up
        continuously as the system stays in use, not just once.

        total_ai_time_ms is the real, measured sum of every agent's
        duration_ms across every ticket ever routed. The manual-minutes
        assumption is intentionally NOT baked in here -- it's kept as a
        user-editable multiplier on the frontend so the comparison
        stays honest about what's measured (AI time) versus assumed
        (manual time).
        """
        session = SessionLocal()
        try:
            total_tickets = session.query(func.count(TicketRecord.id)).scalar() or 0
            total_ai_ms = (
                session.query(func.coalesce(func.sum(AgentTraceRecord.duration_ms), 0.0)).scalar()
                or 0.0
            )
            return {
                "total_tickets_routed": int(total_tickets),
                "total_ai_time_ms": float(total_ai_ms),
            }
        finally:
            session.close()

    def get_analytics_summary(self) -> dict:
        """A business-facing summary across every ticket ever routed --
        answers questions like "which department gets the most tickets,"
        "how trustworthy is the AI's own confidence," and "is workload
        actually spread evenly across the team." Everything here is a
        plain historical aggregate; nothing enforces a deadline or
        threshold (deliberately not an SLA/aging system).

        "Effective" category/priority/team means the admin's correction
        if one was made, otherwise the AI's original call -- this
        reflects what the ticket *actually is* right now, the same way
        the ticket detail views already display it.
        """
        session = SessionLocal()
        try:
            records = (
                session.query(TicketRecord)
                .options(joinedload(TicketRecord.assigned_employee).joinedload(Employee.department))
                .all()
            )
            total = len(records)

            department_counts: dict = {}
            category_counts: dict = {}
            priority_counts: dict = {}
            sentiment_counts: dict = {}
            daily_counts: dict = {}
            employee_workload: dict = {}
            needs_review_count = 0
            override_count = 0
            confidence_sum = 0
            resolution_hours: list = []

            for r in records:
                effective_team = r.admin_team or r.assigned_team
                department = TEAM_TO_DEPARTMENT.get(effective_team, "Unmapped")
                department_counts[department] = department_counts.get(department, 0) + 1

                effective_category = r.admin_category or r.category
                category_counts[effective_category] = category_counts.get(effective_category, 0) + 1

                effective_priority = r.admin_priority or r.priority
                priority_counts[effective_priority] = priority_counts.get(effective_priority, 0) + 1

                sentiment = r.sentiment or "Neutral"
                sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1

                if r.needs_human_review:
                    needs_review_count += 1
                if r.admin_category or r.admin_priority or r.admin_team:
                    override_count += 1
                confidence_sum += r.confidence_score or 0

                if r.created_at:
                    day_key = r.created_at.date().isoformat()
                    daily_counts[day_key] = daily_counts.get(day_key, 0) + 1

                if r.status in ("Resolved", "Closed") and r.created_at and r.updated_at:
                    delta_hours = (r.updated_at - r.created_at).total_seconds() / 3600.0
                    if delta_hours >= 0:
                        resolution_hours.append(delta_hours)

                if r.assigned_employee_id is not None:
                    entry = employee_workload.setdefault(
                        r.assigned_employee_id,
                        {
                            "employee_name": r.assigned_employee.name if r.assigned_employee else "Unknown",
                            "department_name": (
                                r.assigned_employee.department.name
                                if r.assigned_employee and r.assigned_employee.department
                                else "Unknown"
                            ),
                            "open_count": 0,
                            "total_count": 0,
                        },
                    )
                    entry["total_count"] += 1
                    if r.status in ("New", "In Progress"):
                        entry["open_count"] += 1

            return {
                "total_tickets": total,
                "department_counts": department_counts,
                "category_counts": category_counts,
                "priority_counts": priority_counts,
                "sentiment_counts": sentiment_counts,
                "avg_confidence_score": round(confidence_sum / total, 1) if total else 0,
                "pct_needs_human_review": round(needs_review_count / total * 100, 1) if total else 0,
                "pct_admin_override": round(override_count / total * 100, 1) if total else 0,
                "avg_resolution_hours": (
                    round(sum(resolution_hours) / len(resolution_hours), 1) if resolution_hours else None
                ),
                "resolved_sample_size": len(resolution_hours),
                "employee_workload": sorted(
                    employee_workload.values(), key=lambda e: -e["open_count"]
                ),
                "daily_volume": [
                    {"date": d, "count": c} for d, c in sorted(daily_counts.items())[-30:]
                ],
            }
        finally:
            session.close()

    def update_ticket_admin_fields(
        self,
        ticket_id: str,
        status: str,
        resolution_comment: Optional[str] = None,
        admin_category: Optional[str] = None,
        admin_priority: Optional[str] = None,
        admin_team: Optional[str] = None,
        assigned_employee_id: Optional[int] = None,
    ) -> Optional[TicketRecord]:
        """Applies the whole admin management form to a ticket in one
        call. This intentionally replaces all six fields at once
        (rather than skipping ones left as None) because the admin UI
        always submits its complete current form state -- that's what
        lets an admin clear a previous override, or unassign a ticket,
        by simply leaving that field blank and saving again.

        Returns the updated, detached record, or None if the ticket_id
        doesn't exist.
        """
        session = SessionLocal()
        try:
            record = (
                session.query(TicketRecord)
                .options(joinedload(TicketRecord.assigned_employee).joinedload(Employee.department))
                .filter(TicketRecord.id == ticket_id)
                .first()
            )
            if record is None:
                return None

            record.status = status
            record.resolution_comment = resolution_comment
            record.admin_category = admin_category
            record.admin_priority = admin_priority
            record.admin_team = admin_team
            record.assigned_employee_id = assigned_employee_id
            record.updated_at = datetime.utcnow()

            session.commit()
            session.refresh(record)
            if record.assigned_employee is not None:
                _ = record.assigned_employee.department  # load before detaching
            session.expunge(record)
            return record
        finally:
            session.close()

    def list_departments(self) -> List[Department]:
        session = SessionLocal()
        try:
            departments = session.query(Department).order_by(Department.name).all()
            session.expunge_all()
            return departments
        finally:
            session.close()

    def create_department(self, name: str) -> Department:
        session = SessionLocal()
        try:
            existing = session.query(Department).filter(Department.name == name).first()
            if existing is not None:
                raise ValueError(f"Department '{name}' already exists")
            department = Department(name=name)
            session.add(department)
            session.commit()
            session.refresh(department)
            session.expunge(department)
            return department
        finally:
            session.close()

    def list_employees(self, department_id: Optional[int] = None) -> List[Employee]:
        session = SessionLocal()
        try:
            query = session.query(Employee).options(joinedload(Employee.department))
            if department_id is not None:
                query = query.filter(Employee.department_id == department_id)
            employees = query.order_by(Employee.name).all()
            session.expunge_all()
            return employees
        finally:
            session.close()

    def create_employee(
        self,
        name: str,
        department_id: int,
        email: Optional[str] = None,
        role: Optional[str] = None,
    ) -> Optional[Employee]:
        session = SessionLocal()
        try:
            department = session.query(Department).filter(Department.id == department_id).first()
            if department is None:
                return None
            employee = Employee(name=name, email=email, role=role, department_id=department_id)
            session.add(employee)
            session.commit()
            session.refresh(employee)
            _ = employee.department.name  # load before detaching
            session.expunge(employee)
            return employee
        finally:
            session.close()