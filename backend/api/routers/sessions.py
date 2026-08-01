"""`GET /sessions` and `GET /session/{id}` -- api_contracts.md.

Read-only. No endpoint in this package writes to the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession

from backend.api.schemas import SessionDetail, SessionListResponse, SessionSummary
from backend.database.models import Command, Event, FileRecord, Session
from backend.database.session import as_utc, get_db
from backend.shared.events import EventType

router = APIRouter(tags=["sessions"])


def _counts_by_session(db: SASession, model, session_id: str | None = None) -> dict[str, int]:
    """`{session_id: COUNT(*)}` for a child table, optionally for one session.

    Aggregated in a single grouped query rather than per row -- a per-session
    COUNT inside the list loop would be one query per session on a page that
    renders every session the user has.
    """
    stmt = select(model.session_id, func.count()).group_by(model.session_id)
    if session_id is not None:
        stmt = stmt.where(model.session_id == session_id)
    return {row[0]: row[1] for row in db.execute(stmt).all()}


def _to_summary(row: Session, file_counts: dict, command_counts: dict) -> SessionSummary:
    return SessionSummary(
        id=row.id,
        agent=row.agent,
        model=row.model,
        start_time=as_utc(row.start_time),
        end_time=as_utc(row.end_time),
        duration_seconds=row.duration,
        file_count=file_counts.get(row.id, 0),
        command_count=command_counts.get(row.id, 0),
        token_count=row.token_count or 0,
        estimated_cost=row.estimated_cost or 0.0,
        productivity=None,  # Milestone 3 -- never a placeholder number
    )


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(db: SASession = Depends(get_db)) -> SessionListResponse:
    """Every session, newest first. Backs the Sessions page table."""
    rows = db.execute(select(Session).order_by(Session.start_time.desc())).scalars().all()
    file_counts = _counts_by_session(db, FileRecord)
    command_counts = _counts_by_session(db, Command)
    return SessionListResponse(
        sessions=[_to_summary(row, file_counts, command_counts) for row in rows]
    )


@router.get("/session/{session_id}", response_model=SessionDetail)
def get_session(session_id: str, db: SASession = Depends(get_db)) -> SessionDetail:
    """One session's record plus aggregate counts."""
    row = db.get(Session, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")

    file_counts = _counts_by_session(db, FileRecord, session_id)
    command_counts = _counts_by_session(db, Command, session_id)
    summary = _to_summary(row, file_counts, command_counts)

    # One grouped query for all three event-type counts, rather than three.
    by_type = {
        event_type: count
        for event_type, count in db.execute(
            select(Event.event_type, func.count())
            .where(Event.session_id == session_id)
            .group_by(Event.event_type)
        ).all()
    }

    return SessionDetail(
        **summary.model_dump(),
        test_pass_count=by_type.get(EventType.TEST_PASSED.value, 0),
        test_fail_count=by_type.get(EventType.TEST_FAILED.value, 0),
        commit_count=by_type.get(EventType.GIT_COMMIT.value, 0),
    )
