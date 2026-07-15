"""
persistence/repository.py

Hides how data actually gets saved and fetched behind two simple
functions, save() and get_by_id(). Nothing outside this file should
import SQLAlchemy directly -- the orchestrator and API just call this.
"""

import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import case, func, inspect, text
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
        # Same story for created_at (Analytics groups by day off this
        # column on every request) and assigned_employee_id (Analytics'
        # employee-workload aggregate groups by it too) -- both are
        # indexed on the model now, but only a fresh database picks that
        # up automatically via create_all(); an existing one needs the
        # index added explicitly, same as status above.
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tickets_created_at ON tickets (created_at)"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_tickets_assigned_employee_id ON tickets (assigned_employee_id)")
        )


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

# A hard ceiling on list_recent()'s limit param -- GET /tickets exposes
# this directly as a query string value, so without a cap a client could
# request e.g. limit=10000000 and force one enormous query and response.
_MAX_LIST_LIMIT = 1000


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
        customer_name: Optional[str] = None,
        customer_email: Optional[str] = None,
    ) -> None:
        session = SessionLocal()
        try:
            # If this exact ticket_id was already saved and already has
            # an assignment (whether auto-picked or set by an admin),
            # keep it -- save() can in principle be called again for the
            # same id, and a re-save should never silently wipe out an
            # existing assignment or an admin's status change.
            existing = session.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
            # A satisfaction rating is given well after routing, through
            # a completely separate call (record_satisfaction_rating
            # below) -- a re-save here must never quietly erase it.
            existing_satisfaction_rating = existing.satisfaction_rating if existing is not None else None
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
                customer_name=customer_name,
                customer_email=customer_email,
                satisfaction_rating=existing_satisfaction_rating,
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

    def set_satisfaction_rating(self, ticket_id: str, rating: int) -> Optional[TicketRecord]:
        """Records a customer's post-resolution satisfaction rating (1-5).
        Only makes sense once a ticket has actually reached Resolved/Closed
        -- callers (the API route) are expected to enforce that; this
        method's own job is just the write + the range check, so it stays
        safe to call regardless of who ends up calling it.
        Returns the updated record, or None if the ticket doesn't exist.
        """
        if rating < 1 or rating > 5:
            raise ValueError("Satisfaction rating must be between 1 and 5.")
        session = SessionLocal()
        try:
            record = session.query(TicketRecord).filter(TicketRecord.id == ticket_id).first()
            if record is None:
                return None
            record.satisfaction_rating = rating
            session.commit()
            session.refresh(record)
            return record
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

        limit is capped server-side (see _MAX_LIST_LIMIT) regardless of
        what a caller passes -- the API route exposes this as a query
        param, and without a hard ceiling here a client could ask for an
        enormous number and force one huge query/response.
        """
        # SQLite treats a negative LIMIT as "no limit at all" -- clamp the
        # lower bound too, not just the upper one, so a caller passing
        # limit=-1 can't accidentally bypass the cap entirely.
        limit = max(1, min(limit, _MAX_LIST_LIMIT))
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

        This does every count/average as a SQL aggregate (GROUP BY / AVG
        / COUNT) instead of pulling every ticket row into Python and
        summing there. At demo scale (dozens/hundreds of tickets) the two
        approaches feel identical; at real scale (thousands+) loading
        every row just to add them up in a loop is the kind of thing that
        quietly becomes the slowest endpoint in the app, so this does the
        adding in the database instead, where it belongs.
        """
        session = SessionLocal()
        try:
            total = session.query(func.count(TicketRecord.id)).scalar() or 0
            if total == 0:
                return {
                    "total_tickets": 0,
                    "department_counts": {},
                    "category_counts": {},
                    "priority_counts": {},
                    "sentiment_counts": {},
                    "avg_confidence_score": 0,
                    "pct_needs_human_review": 0,
                    "pct_admin_override": 0,
                    "avg_resolution_hours": None,
                    "resolved_sample_size": 0,
                    "avg_satisfaction_rating": None,
                    "satisfaction_sample_size": 0,
                    "employee_workload": [],
                    "daily_volume": [],
                }

            effective_category = func.coalesce(TicketRecord.admin_category, TicketRecord.category)
            effective_priority = func.coalesce(TicketRecord.admin_priority, TicketRecord.priority)
            effective_team = func.coalesce(TicketRecord.admin_team, TicketRecord.assigned_team)
            effective_sentiment = func.coalesce(TicketRecord.sentiment, "Neutral")

            category_counts = dict(
                session.query(effective_category, func.count(TicketRecord.id))
                .group_by(effective_category)
                .all()
            )
            priority_counts = dict(
                session.query(effective_priority, func.count(TicketRecord.id))
                .group_by(effective_priority)
                .all()
            )
            sentiment_counts = dict(
                session.query(effective_sentiment, func.count(TicketRecord.id))
                .group_by(effective_sentiment)
                .all()
            )

            # TEAM_TO_DEPARTMENT is an application-level mapping, not a DB
            # table, so this still does the count in SQL (one GROUP BY by
            # team) and only remaps team -> department in Python afterward
            # -- a handful of rows, not thousands.
            team_counts = dict(
                session.query(effective_team, func.count(TicketRecord.id))
                .group_by(effective_team)
                .all()
            )
            department_counts: dict = {}
            for team, count in team_counts.items():
                dept = TEAM_TO_DEPARTMENT.get(team, "Unmapped")
                department_counts[dept] = department_counts.get(dept, 0) + count

            needs_review_count = (
                session.query(func.count(TicketRecord.id))
                .filter(TicketRecord.needs_human_review.is_(True))
                .scalar()
                or 0
            )
            override_count = (
                session.query(func.count(TicketRecord.id))
                .filter(
                    (TicketRecord.admin_category.isnot(None))
                    | (TicketRecord.admin_priority.isnot(None))
                    | (TicketRecord.admin_team.isnot(None))
                )
                .scalar()
                or 0
            )
            avg_confidence = session.query(func.avg(TicketRecord.confidence_score)).scalar()
            avg_satisfaction, satisfaction_n = session.query(
                func.avg(TicketRecord.satisfaction_rating),
                func.count(TicketRecord.satisfaction_rating),
            ).one()

            # SQLite has no native "hours between two timestamps" -- but
            # julianday() turns a timestamp into a day-count float, so
            # subtracting and multiplying by 24 gets hours without ever
            # pulling the raw datetimes into Python.
            resolution_expr = (
                func.julianday(TicketRecord.updated_at) - func.julianday(TicketRecord.created_at)
            ) * 24.0
            resolution_rows = (
                session.query(resolution_expr)
                .filter(
                    TicketRecord.status.in_(["Resolved", "Closed"]),
                    TicketRecord.created_at.isnot(None),
                    TicketRecord.updated_at.isnot(None),
                )
                .all()
            )
            resolution_hours = [row[0] for row in resolution_rows if row[0] is not None and row[0] >= 0]

            day_expr = func.date(TicketRecord.created_at)
            daily_rows = (
                session.query(day_expr, func.count(TicketRecord.id))
                .group_by(day_expr)
                .order_by(day_expr)
                .all()
            )
            daily_volume = [{"date": d, "count": c} for d, c in daily_rows][-30:]

            open_case = case((TicketRecord.status.in_(["New", "In Progress"]), 1), else_=0)
            workload_rows = (
                session.query(
                    Employee.name,
                    Department.name,
                    func.count(TicketRecord.id),
                    func.sum(open_case),
                )
                .join(Employee, Employee.id == TicketRecord.assigned_employee_id)
                .outerjoin(Department, Department.id == Employee.department_id)
                .filter(TicketRecord.assigned_employee_id.isnot(None))
                .group_by(Employee.id, Employee.name, Department.name)
                .all()
            )
            employee_workload = sorted(
                (
                    {
                        "employee_name": employee_name or "Unknown",
                        "department_name": department_name or "Unknown",
                        "open_count": int(open_count or 0),
                        "total_count": int(total_count or 0),
                    }
                    for employee_name, department_name, total_count, open_count in workload_rows
                ),
                key=lambda e: -e["open_count"],
            )

            return {
                "total_tickets": total,
                "department_counts": department_counts,
                "category_counts": category_counts,
                "priority_counts": priority_counts,
                "sentiment_counts": sentiment_counts,
                "avg_confidence_score": round(avg_confidence, 1) if avg_confidence is not None else 0,
                "pct_needs_human_review": round(needs_review_count / total * 100, 1) if total else 0,
                "pct_admin_override": round(override_count / total * 100, 1) if total else 0,
                "avg_resolution_hours": (
                    round(sum(resolution_hours) / len(resolution_hours), 1) if resolution_hours else None
                ),
                "resolved_sample_size": len(resolution_hours),
                "avg_satisfaction_rating": (
                    round(avg_satisfaction, 1) if avg_satisfaction is not None else None
                ),
                "satisfaction_sample_size": int(satisfaction_n or 0),
                "employee_workload": employee_workload,
                "daily_volume": daily_volume,
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