"""`GET /timeline/{id}` -- the session replay view (PRD section 14)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as SASession

from backend.api.labels import label_for
from backend.api.schemas import TimelineEvent, TimelineResponse
from backend.database.models import Event, Session
from backend.database.session import as_utc, get_db

router = APIRouter(tags=["timeline"])


@router.get("/timeline/{session_id}", response_model=TimelineResponse)
def get_timeline(session_id: str, db: SASession = Depends(get_db)) -> TimelineResponse:
    """Ordered event sequence for one session.

    404s on an unknown session rather than returning an empty timeline, so the
    dashboard can tell "no such session" apart from "session with no events yet".
    """
    if db.get(Session, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")

    rows = (
        db.execute(
            select(Event)
            .where(Event.session_id == session_id)
            .order_by(Event.timestamp.asc(), Event.id.asc())
        )
        .scalars()
        .all()
    )

    return TimelineResponse(
        session_id=session_id,
        events=[
            TimelineEvent(
                timestamp=as_utc(row.timestamp),
                event_type=row.event_type,
                label=label_for(row.event_type, row.file, row.metadata_),
                file=row.file,
                metadata=row.metadata_ or {},
            )
            for row in rows
        ],
    )
