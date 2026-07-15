"""
persistence/database.py

Sets up the actual database connection. Every other file in this
folder builds on top of this one; nothing outside this folder should
import SQLAlchemy directly.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from ticket_router.config.settings import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)

# SQLite's default journal mode makes a single writer block every
# reader for the duration of a write -- fine for a quick demo, but the
# first thing that bites you under any real concurrent load (e.g. the
# Admin board polling while a customer submits a ticket). WAL
# (write-ahead logging) lets reads and a write happen at the same time
# instead. synchronous=NORMAL is the standard pairing with WAL: still
# safe against corruption on a crash, it just skips some fsync calls
# that matter far more under the older rollback-journal mode. Both are
# no-ops (harmless) if this is ever pointed at a non-SQLite database.
if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)