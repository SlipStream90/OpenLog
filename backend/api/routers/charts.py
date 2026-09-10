"""`GET /charts` -- per-day aggregates for the Home charts (PRD §14).

Read-only. Buckets sessions by the user's local date (same "today" rule as
`/stats`) and sums duration/tokens/cost per day, so the dashboard can draw
coding-time, session, cost and token series without any new tables.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as SASession

from backend.api.schemas import ChartPoint, ChartsResponse
from backend.database.models import Session
from backend.database.session import as_utc, get_db
from backend.shared.timeutil import utcnow

router = APIRouter(tags=["charts"])

RANGES = {"7d": 7, "30d": 30}


@router.get("/charts", response_model=ChartsResponse)
def get_charts(
    range_param: str = Query("7d", alias="range"),  # noqa: B008
    db: SASession = Depends(get_db),  # noqa: B008
) -> ChartsResponse:
    """`range` is `7d` or `30d` (anything else is a 400). Days with no
    sessions are returned as zero points so charts render continuously."""
    days = RANGES.get(range_param)
    if days is None:
        raise HTTPException(
            status_code=400, detail=f"range must be one of {sorted(RANGES)}"
        )

    now_local = datetime.now().astimezone()
    today = now_local.date()
    start_local = datetime.combine(
        today - timedelta(days=days - 1), time.min, tzinfo=now_local.tzinfo
    )
    cutoff_utc = start_local.astimezone(UTC)

    rows = (
        db.execute(select(Session).where(Session.start_time >= cutoff_utc))
        .scalars()
        .all()
    )

    buckets: dict[str, dict] = {}
    for offset in range(days):
        label = (today - timedelta(days=days - 1 - offset)).isoformat()
        buckets[label] = {"sessions": 0, "seconds": 0.0, "tokens": 0, "cost": 0.0}

    now = utcnow()
    for row in rows:
        started = as_utc(row.start_time)
        label = started.astimezone(now_local.tzinfo).date().isoformat()
        bucket = buckets.get(label)
        if bucket is None:
            continue
        bucket["sessions"] += 1
        if row.duration is not None:
            bucket["seconds"] += row.duration
        else:
            # In progress: count elapsed, same rule as /stats.
            bucket["seconds"] += max((now - started).total_seconds(), 0.0)
        bucket["tokens"] += row.token_count or 0
        bucket["cost"] += row.estimated_cost or 0.0

    return ChartsResponse(
        range=range_param,
        points=[
            ChartPoint(
                date=label,
                sessions=b["sessions"],
                seconds=round(b["seconds"], 2),
                tokens=b["tokens"],
                cost=round(b["cost"], 4),
            )
            for label, b in buckets.items()
        ],
    )
