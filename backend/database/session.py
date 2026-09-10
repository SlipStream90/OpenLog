"""Engine, session factory and first-run initialization.

Concurrency model (ARCHITECTURE.md section 4, ADR-005): SQLite in WAL mode so the
API's read queries never block on the single ingestion writer coroutine.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base
from backend.shared import paths

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[SASession] | None = None


def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    """Apply per-connection pragmas.

    WAL is a persistent database property, but `synchronous` is per-connection,
    so both are set on every connect rather than once at creation.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Rather than failing instantly on a momentarily-held write lock, wait.
        # Cheap insurance: the writer is single, but a checkpoint can still
        # overlap a read.
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def get_engine() -> Engine:
    """Process-wide engine, created on first use."""
    global _engine
    if _engine is None:
        paths.ensure_directories()
        db_path = paths.database_path()
        _engine = create_engine(
            f"sqlite:///{db_path}",
            # Needed because the ingestion writer coroutine and the API's request
            # handlers reach SQLite from different threads of the same process.
            connect_args={"check_same_thread": False},
            future=True,
        )
        event.listen(_engine, "connect", _configure_sqlite)
        logger.debug("SQLite engine created at %s", db_path)
    return _engine


def get_session_factory() -> sessionmaker[SASession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), expire_on_commit=False, future=True
        )
    return _session_factory


def init_db() -> None:
    """Create the local storage tree and all tables. Idempotent."""
    paths.ensure_directories()
    Base.metadata.create_all(get_engine())
    logger.info("Database initialized at %s", paths.database_path())


def reset_engine() -> None:
    """Drop the cached engine/factory.

    Exists so tests can repoint `AI_OBSERVATORY_HOME` at a temp directory
    between cases without leaking a connection to a previous database.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def session_scope() -> Iterator[SASession]:
    """Transactional scope for a series of operations."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[SASession]:
    """FastAPI dependency yielding a read-only-by-convention session.

    The API layer never writes (api_contracts.md), so this does not commit.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def as_utc(value):
    """Re-attach UTC to a datetime SQLite handed back as naive.

    SQLite has no datetime type; values round-trip as strings and come back
    without tzinfo. Serializing those directly would emit timestamps with no
    offset, which the dashboard would then render in the browser's local zone --
    silently shifting every event on the timeline.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
