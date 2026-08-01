"""`GET /stats` -- today's raw aggregates for the Home page.

Raw aggregates only. No productivity score: that is Milestone 3, and the field is
deliberately *absent* rather than null (api_contracts.md), so nothing in the UI
can accidentally render a fabricated zero.
"""

from __future__ import annotations

from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession

from backend.adapters.claude import pricing
from backend.api.schemas import StatsResponse, WatcherStatusModel
from backend.database.models import Command, Event, FileRecord, Session
from backend.database.session import as_utc, get_db
from backend.shared.events import TEST_EVENT_TYPES
from backend.shared.timeutil import utcnow
from backend.telemetry.watcher_status import registry

router = APIRouter(tags=["stats"])


def _today_bounds() -> tuple[datetime, datetime, str]:
    """Local-midnight-to-midnight, expressed in UTC for querying.

    "Today" means the user's local day -- a session at 11pm belongs to the day
    the developer experienced, not to UTC's. Timestamps are stored in UTC, so the
    local boundaries are converted rather than the rows.
    """
    now_local = datetime.now().astimezone()
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=now_local.tzinfo)
    end_local = datetime.combine(now_local.date(), time.max, tzinfo=now_local.tzinfo)
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
        now_local.date().isoformat(),
    )


@router.get("/stats", response_model=StatsResponse)
def get_stats(db: SASession = Depends(get_db)) -> StatsResponse:
    start_utc, end_utc, date_label = _today_bounds()

    sessions = (
        db.execute(
            select(Session).where(
                Session.start_time >= start_utc, Session.start_time <= end_utc
            )
        )
        .scalars()
        .all()
    )
    session_ids = [row.id for row in sessions]

    now = utcnow()
    coding_time = 0.0
    estimated_cost = 0.0
    for row in sessions:
        if row.duration is not None:
            coding_time += row.duration
        else:
            # Still in progress: count elapsed time so the Home page reflects the
            # session the developer is in right now, not just finished ones.
            started = as_utc(row.start_time)
            coding_time += max((now - started).total_seconds(), 0.0)
        estimated_cost += row.estimated_cost or 0.0

    files_changed = 0
    command_count = 0
    test_count = 0
    if session_ids:
        files_changed = (
            db.execute(
                select(func.count(func.distinct(FileRecord.filename))).where(
                    FileRecord.session_id.in_(session_ids)
                )
            ).scalar()
            or 0
        )
        command_count = (
            db.execute(
                select(func.count()).where(Command.session_id.in_(session_ids))
            ).scalar()
            or 0
        )
        test_count = (
            db.execute(
                select(func.count()).where(
                    Event.session_id.in_(session_ids),
                    Event.event_type.in_([t.value for t in TEST_EVENT_TYPES]),
                )
            ).scalar()
            or 0
        )

    return StatsResponse(
        date=date_label,
        coding_time_seconds=round(coding_time, 2),
        session_count=len(sessions),
        files_changed_count=int(files_changed),
        estimated_cost=round(estimated_cost, 4),
        command_count=int(command_count),
        test_count=int(test_count),
        cost_is_estimated=pricing.is_priced(),
        watchers={
            name: WatcherStatusModel(**data) for name, data in registry.snapshot().items()
        },
    )
