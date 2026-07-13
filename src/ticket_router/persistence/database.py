"""
persistence/database.py

Sets up the actual database connection. Every other file in this
folder builds on top of this one; nothing outside this folder should
import SQLAlchemy directly.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ticket_router.config.settings import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)