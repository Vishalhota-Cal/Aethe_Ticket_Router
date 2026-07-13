"""
tests/conftest.py

Shared test setup: forces the mock LLM provider (no real API key or
network call needed) and a disposable test database, before any
application code is imported -- then provides a couple of reusable
fixtures for the tests below.
"""

import os

os.environ["LLM_PROVIDER"] = "mock"
os.environ["DATABASE_URL"] = "sqlite:///./test_ticket_router.db"

import pytest
from fastapi.testclient import TestClient

from ticket_router.api.main import app
from ticket_router.domain.models import Ticket


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_ticket() -> Ticket:
    return Ticket(
        id="482",
        subject="Can't log in - urgent, demo in 30 minutes",
        description=(
            "I've been locked out of my account for the last 2 hours. "
            "I have a client demo in 30 minutes and really need this fixed immediately."
        ),
    )