"""
api/main.py

Builds the actual FastAPI application: configures logging, mounts
every route file, serves the standalone HTML frontend at "/", and
returns one runnable app object.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from ticket_router.api.routes import admin, employees, health, stats, tickets
from ticket_router.observability.logging_config import configure_logging

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(title="AI Smart Ticket Router")
    app.include_router(tickets.router)
    app.include_router(admin.router)
    app.include_router(employees.router)
    app.include_router(stats.router)
    app.include_router(health.router)

    @app.get("/", include_in_schema=False)
    async def serve_ui() -> FileResponse:
        return FileResponse(UI_DIR / "index.html")

    return app


app = create_app()