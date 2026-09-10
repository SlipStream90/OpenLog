"""`GET /search` -- substring search across the local database (PRD §14).

Read-only. Searches filenames, (redacted) command text, and session
id/agent. Results are capped per scope so one broad query cannot dump the
whole database into a response.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as SASession

from backend.api.schemas import (
    SearchCommand,
    SearchResponse,
    SearchSession,
)
from backend.database.models import Command, FileRecord, Session
from backend.database.session import as_utc, get_db

router = APIRouter(tags=["search"])

VALID_SCOPES = ("files", "commands", "sessions")
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = "",
    scope: str = "files,commands,sessions",
    limit: int = DEFAULT_LIMIT,
    db: SASession = Depends(get_db),  # noqa: B008
) -> SearchResponse:
    """Substring match on `q` within the requested scopes.

    An empty query returns empty lists (never the whole database).
    Unknown scope names are ignored; `limit` is clamped to [1, 100].
    """
    query = q.strip()
    limit = max(1, min(limit, MAX_LIMIT))
    scopes = {s.strip().lower() for s in scope.split(",")} & set(VALID_SCOPES)
    if not query or not scopes:
        return SearchResponse(query=query)

    like = f"%{query}%"
    files: list[str] = []
    commands: list[SearchCommand] = []
    sessions: list[SearchSession] = []

    if "files" in scopes:
        rows = (
            db.execute(
                select(FileRecord.filename)
                .where(FileRecord.filename.like(like))
                .group_by(FileRecord.filename)
                .order_by(FileRecord.filename.asc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        files = list(rows)

    if "commands" in scopes:
        rows = (
            db.execute(
                select(Command)
                .where(Command.command.like(like))
                .order_by(Command.timestamp.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        commands = [
            SearchCommand(
                command=row.command,
                session_id=row.session_id,
                timestamp=as_utc(row.timestamp),
                exit_code=row.exit_code,
            )
            for row in rows
        ]

    if "sessions" in scopes:
        rows = (
            db.execute(
                select(Session)
                .where((Session.id.like(like)) | (Session.agent.like(like)))
                .order_by(Session.start_time.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        sessions = [
            SearchSession(
                id=row.id, agent=row.agent, start_time=as_utc(row.start_time)
            )
            for row in rows
        ]

    return SearchResponse(query=query, files=files, commands=commands, sessions=sessions)
