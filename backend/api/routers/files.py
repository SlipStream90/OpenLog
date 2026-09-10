"""`GET /files` -- cross-session file aggregate."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession

from backend.api.schemas import FileAggregate, FileListResponse
from backend.database.models import FileRecord
from backend.database.session import as_utc, get_db

router = APIRouter(tags=["files"])


@router.get("/files", response_model=FileListResponse)
def list_files(db: SASession = Depends(get_db)) -> FileListResponse:  # noqa: B008
    """Per-filename totals across every session, most-modified first."""
    rows = db.execute(
        select(
            FileRecord.filename,
            func.count(func.distinct(FileRecord.session_id)),
            func.coalesce(func.sum(FileRecord.additions), 0),
            func.coalesce(func.sum(FileRecord.deletions), 0),
            func.coalesce(func.sum(FileRecord.modifications), 0),
            func.max(FileRecord.last_modified),
        )
        .group_by(FileRecord.filename)
        .order_by(func.coalesce(func.sum(FileRecord.modifications), 0).desc())
    ).all()

    return FileListResponse(
        files=[
            FileAggregate(
                filename=filename,
                session_count=session_count,
                total_additions=int(additions or 0),
                total_deletions=int(deletions or 0),
                total_modifications=int(modifications or 0),
                last_modified=as_utc(last_modified),
            )
            for (
                filename,
                session_count,
                additions,
                deletions,
                modifications,
                last_modified,
            ) in rows
        ]
    )
