"""`GET /export` -- download tables as JSON or CSV (PRD §23).

Read-only. Serializes the existing tables; row-capped so an export cannot
blow up memory on a year-old database. CSV responses carry
`Content-Disposition: attachment` so browsers download rather than render.
"""

from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as SASession

from backend.database.models import Command, Event, FileRecord, Prompt, Session
from backend.database.session import as_utc, get_db

router = APIRouter(tags=["export"])

TABLES = ("sessions", "events", "files", "commands", "prompts")
FORMATS = ("json", "csv")
MAX_ROWS = 10_000


def _iso(value) -> str | None:
    if value is None:
        return None
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _rows(table: str, db: SASession) -> tuple[list[str], list[list]]:
    """(header, rows) of plain values for `table`, newest last, capped."""
    if table == "sessions":
        header = ["id", "agent", "model", "start_time", "end_time", "duration",
                  "token_count", "estimated_cost"]
        data = db.execute(select(Session).order_by(Session.start_time.asc()).limit(MAX_ROWS)).scalars().all()
        rows = [[r.id, r.agent, r.model, _iso(r.start_time), _iso(r.end_time),
                 r.duration, r.token_count, r.estimated_cost] for r in data]
    elif table == "events":
        header = ["id", "session_id", "timestamp", "event_type", "file", "metadata"]
        data = db.execute(select(Event).order_by(Event.id.asc()).limit(MAX_ROWS)).scalars().all()
        rows = [[r.id, r.session_id, _iso(r.timestamp), r.event_type, r.file,
                 json.dumps(r.metadata_ or {})] for r in data]
    elif table == "files":
        header = ["session_id", "filename", "additions", "deletions",
                  "modifications", "last_modified"]
        data = db.execute(select(FileRecord).order_by(FileRecord.id.asc()).limit(MAX_ROWS)).scalars().all()
        rows = [[r.session_id, r.filename, r.additions, r.deletions,
                 r.modifications, _iso(r.last_modified)] for r in data]
    elif table == "commands":
        header = ["session_id", "command", "timestamp", "exit_code"]
        data = db.execute(select(Command).order_by(Command.id.asc()).limit(MAX_ROWS)).scalars().all()
        rows = [[r.session_id, r.command, _iso(r.timestamp), r.exit_code] for r in data]
    else:  # prompts
        header = ["session_id", "prompt_length", "timestamp"]
        data = db.execute(select(Prompt).order_by(Prompt.id.asc()).limit(MAX_ROWS)).scalars().all()
        rows = [[r.session_id, r.prompt_length, _iso(r.timestamp)] for r in data]
    return header, rows


@router.get("/export")
def export_table(
    table: str = "sessions",
    format: str = "json",  # noqa: A002 -- query param name is the API contract
    db: SASession = Depends(get_db),  # noqa: B008
):
    """Download `table` in `format`. 400 on unknown table/format."""
    if table not in TABLES:
        raise HTTPException(status_code=400, detail=f"table must be one of {list(TABLES)}")
    if format not in FORMATS:
        raise HTTPException(status_code=400, detail=f"format must be one of {list(FORMATS)}")

    header, rows = _rows(table, db)
    filename = f"openlog-{table}.{format}"
    if format == "json":
        body = json.dumps(
            {"table": table, "rows": [dict(zip(header, row)) for row in rows]},
            indent=2,
        )
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
