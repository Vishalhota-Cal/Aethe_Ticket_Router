"""
api/routes/health.py

A simple endpoint so monitoring tools (or you) can check the service
is running, without submitting a real ticket.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}