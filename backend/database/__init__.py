"""Database layer: SQLAlchemy models, engine setup and first-run initialization."""

from backend.database.models import (
    Base,
    Command,
    Event,
    FileRecord,
    Prompt,
    Session,
)
from backend.database.session import (
    as_utc,
    get_db,
    get_engine,
    get_session_factory,
    init_db,
    reset_engine,
    session_scope,
)

__all__ = [
    "Base",
    "Command",
    "Event",
    "FileRecord",
    "Prompt",
    "Session",
    "as_utc",
    "get_db",
    "get_engine",
    "get_session_factory",
    "init_db",
    "reset_engine",
    "session_scope",
]
