"""SQLAlchemy models -- PRD section 13 schema, data_models.md section 4.

Deliberately absent: a `Statistics` model. That table holds analytics-engine
output and belongs to Milestone 3 (MISSION_BRIEF.md line 39). Do not add it here
"just as a stub".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every AI Observatory table."""


#: SQLite has no native tz-aware datetime; SQLAlchemy stores what it is given and
#: returns it naive. Every read path re-attaches UTC via `backend.database.session`.
_UTCDateTime = DateTime(timezone=True)


class Session(Base):
    """One AI coding session, keyed by the agent's own session id.

    Upserted on *every* event, not created once: whichever source (hook or
    transcript) observes a session id first creates the row, and later events
    from either source enrich it. See ARCHITECTURE.md section 3.
    """

    __tablename__ = "sessions"

    # The agent's own session id is used directly as the PK -- no surrogate key.
    # It is the reconciliation key between the two independent data sources
    # (ADR-001), so a second identifier would only create a chance for them to
    # disagree.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    start_time: Mapped[datetime] = mapped_column(_UTCDateTime, index=True)
    end_time: Mapped[datetime | None] = mapped_column(_UTCDateTime, nullable=True)
    #: Seconds. Computed at write time so the read path stays a plain SELECT.
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent: Mapped[str] = mapped_column(String, index=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")


class Event(Base):
    """The append-only log every other table is derived from."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id"), index=True
    )
    timestamp: Mapped[datetime] = mapped_column(_UTCDateTime, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    file: Mapped[str | None] = mapped_column(String, nullable=True)
    # `metadata` is reserved on DeclarativeBase, so the Python attribute is
    # `metadata_` while the SQL column keeps PRD section 13's name, `metadata`.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    __table_args__ = (Index("ix_events_session_ts", "session_id", "timestamp"),)


class FileRecord(Base):
    """Per-session file touch counts. Upserted by session_id + filename."""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id"), index=True
    )
    filename: Mapped[str] = mapped_column(String, index=True)
    additions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deletions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    modifications: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_modified: Mapped[datetime | None] = mapped_column(_UTCDateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("session_id", "filename", name="uq_files_session_filename"),
    )


class Command(Base):
    """One terminal command observed during a session."""

    __tablename__ = "commands"

    # ADR-003: PRD section 13 lists no `id` for this table, but SQLAlchemy
    # Declarative requires a primary key. Mechanical ORM requirement, not a
    # schema redesign -- no PRD column is removed or renamed.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id"), index=True
    )
    command: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(_UTCDateTime, index=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Prompt(Base):
    """One submitted prompt -- LENGTH ONLY.

    Prompt text is never stored. This is a hard privacy constraint (PRD section
    21, ARCHITECTURE.md section 6), not an implementation detail: no code path in
    `backend/` may add a column or metadata key holding prompt or response text.
    """

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # ADR-003
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("sessions.id"), index=True
    )
    prompt_length: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(_UTCDateTime, index=True)
