"""`GET /sessions` and `GET /session/{id}` -- api_contracts.md.

Read-only. No endpoint in this package writes to the database.
"""

from __future__ import annotations

from datetime import UTC, datetime, time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession

from backend.analytics.productivity import ScoredProductivity, SessionFactors, score_session
from backend.api.schemas import SessionDetail, SessionListResponse, SessionSummary
from backend.database.models import Command, Event, FileRecord, Prompt, Session
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


def _to_summary(
    row: Session,
    file_counts: dict,
    command_counts: dict,
    productivity: dict[str, ScoredProductivity | None] | None = None,
) -> SessionSummary:
    scored = (productivity or {}).get(row.id)
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
        productivity=float(scored.score) if scored is not None else None,
        productivity_reasons=list(scored.reasons) if scored is not None else [],
    )


def _productivity_for(db: SASession, rows: list[Session]) -> dict[str, ScoredProductivity | None]:
    """Score every listed session from grouped aggregates (3 queries total)."""
    ids = [row.id for row in rows]
    if not ids:
        return {}

    type_counts: dict[tuple[str, str], int] = {
        (sid, etype): count
        for sid, etype, count in db.execute(
            select(Event.session_id, Event.event_type, func.count())
            .where(Event.session_id.in_(ids))
            .group_by(Event.session_id, Event.event_type)
        ).all()
    }
    prompt_stats: dict[str, tuple[int, float]] = {
        sid: (count, float(avg or 0.0))
        for sid, count, avg in db.execute(
            select(Prompt.session_id, func.count(), func.avg(Prompt.prompt_length))
            .where(Prompt.session_id.in_(ids))
            .group_by(Prompt.session_id)
        ).all()
    }
    file_rows: dict[str, int] = _counts_by_session(db, FileRecord)

    def count(sid: str, event: EventType) -> int:
        return type_counts.get((sid, event.value), 0)

    scored: dict[str, ScoredProductivity | None] = {}
    for row in rows:
        prompt_count, prompt_avg = prompt_stats.get(row.id, (0, 0.0))
        scored[row.id] = score_session(
            SessionFactors(
                completed=row.end_time is not None,
                duration_seconds=row.duration or 0.0,
                commits=count(row.id, EventType.GIT_COMMIT),
                tests_passed=count(row.id, EventType.TEST_PASSED),
                tests_failed=count(row.id, EventType.TEST_FAILED),
                tests_executed=count(row.id, EventType.TEST_EXECUTED),
                prompts=prompt_count,
                avg_prompt_length=prompt_avg,
                distinct_files=file_rows.get(row.id, 0),
                edits=count(row.id, EventType.FILE_MODIFIED),
                errors=count(row.id, EventType.ERROR),
                commands=count(row.id, EventType.TERMINAL_COMMAND),
            )
        )
    return scored


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(
    agent: str | None = None,
    date: str | None = None,
    db: SASession = Depends(get_db),  # noqa: B008
) -> SessionListResponse:
    """Every session, newest first. Backs the Sessions page table.

    `agent` filters to one agent (`claude`, `opencode`, `kilocode`).
    `date` (YYYY-MM-DD, the user's local day) keeps sessions started that day.
    A malformed date is a 400, never a silent empty list.
    """
    stmt = select(Session).order_by(Session.start_time.desc())
    if agent:
        stmt = stmt.where(Session.agent == agent.strip().lower())
    if date:
        try:
            day = datetime.strptime(date.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=400, detail="date must be YYYY-MM-DD"
            ) from None
        now_local = datetime.now().astimezone()
        start_local = datetime.combine(day, time.min, tzinfo=now_local.tzinfo)
        end_local = datetime.combine(day, time.max, tzinfo=now_local.tzinfo)
        stmt = stmt.where(
            Session.start_time >= start_local.astimezone(UTC),
            Session.start_time <= end_local.astimezone(UTC),
        )
    rows = db.execute(stmt).scalars().all()
    file_counts = _counts_by_session(db, FileRecord)
    command_counts = _counts_by_session(db, Command)
    productivity = _productivity_for(db, list(rows))
    return SessionListResponse(
        sessions=[
            _to_summary(row, file_counts, command_counts, productivity) for row in rows
        ]
    )


@router.get("/session/{session_id}", response_model=SessionDetail)
def get_session(session_id: str, db: SASession = Depends(get_db)) -> SessionDetail:  # noqa: B008
    """One session's record plus aggregate counts."""
    row = db.get(Session, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")

    file_counts = _counts_by_session(db, FileRecord, session_id)
    command_counts = _counts_by_session(db, Command, session_id)
    summary = _to_summary(row, file_counts, command_counts, _productivity_for(db, [row]))

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
