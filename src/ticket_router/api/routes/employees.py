"""
api/routes/employees.py

A lightweight, HR-style directory: departments and the employees inside
them. This isn't a real HR system -- it exists so a ticket can be
assigned to a specific person (not just a team/queue), and so the
Admin View has somewhere to manage who's available to assign to.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ticket_router.api.dependencies import get_repository
from ticket_router.persistence.repository import TicketRepository

router = APIRouter()


class DepartmentCreate(BaseModel):
    name: str


class EmployeeCreate(BaseModel):
    name: str
    department_id: int
    email: Optional[str] = None
    role: Optional[str] = None


@router.get("/departments")
async def list_departments(repository: TicketRepository = Depends(get_repository)):
    departments = repository.list_departments()
    return [{"id": d.id, "name": d.name} for d in departments]


@router.post("/departments")
async def create_department(
    payload: DepartmentCreate,
    repository: TicketRepository = Depends(get_repository),
):
    try:
        department = repository.create_department(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": department.id, "name": department.name}


@router.get("/employees")
async def list_employees(
    department_id: Optional[int] = None,
    repository: TicketRepository = Depends(get_repository),
):
    employees = repository.list_employees(department_id=department_id)
    return [_serialize_employee(e) for e in employees]


@router.post("/employees")
async def create_employee(
    payload: EmployeeCreate,
    repository: TicketRepository = Depends(get_repository),
):
    employee = repository.create_employee(
        name=payload.name,
        department_id=payload.department_id,
        email=payload.email,
        role=payload.role,
    )
    if employee is None:
        raise HTTPException(status_code=400, detail="No department exists with that department_id")
    return _serialize_employee(employee)


def _serialize_employee(e) -> dict:
    return {
        "id": e.id,
        "name": e.name,
        "email": e.email,
        "role": e.role,
        "active": e.active,
        "department_id": e.department_id,
        "department_name": e.department.name if e.department else None,
    }