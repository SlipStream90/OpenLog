"""Single-writer ingestion pipeline -- ADR-005, ADR-006.

Both watchers push `UniversalEvent`s onto one `asyncio.Queue`; one consumer
coroutine drains it and performs every database write. That removes concurrent
SQLite writers entirely (rather than handling lock contention with retries) and
keeps write ordering deterministic per session.

The actual SQLAlchemy calls are synchronous, so the consumer offloads them with
`asyncio.to_thread` -- blocking the event loop here would stall both watchers and
the API's request handling in the same process.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session as SASession

from backend.database.models import Command, Event, FileRecord, Prompt, Session
from backend.database.session import as_utc, session_scope
from backend.shared.events import FILE_EVENT_TYPES, EventType, UniversalEvent
from backend.telemetry.watcher_status import registry

logger = logging.getLogger(__name__)

#: Bounded so a large transcript backfill cannot grow memory without limit; the
#: watchers await space instead, which naturally throttles them.
QUEUE_MAX_SIZE = 10_000

#: Events drained per transaction. Batching cuts commit overhead during backfill
#: while staying small enough that a crash loses very little.
BATCH_SIZE = 100

#: review_report.md F-2: the writer wasn't enrolled in the watcher registry, so
#: a persist failure (e.g. F-1) was silent -- the dashboard's degraded banner
#: reads /stats, which reads this registry, and an unregistered watcher never
#: appears there at all even while every batch fails.
NAME = "ingestion_writer"


def _upsert_session(db: SASession, event: UniversalEvent, cost: float = 0.0) -> Session:
    """Create or enrich the session row for this event.

    Upserted on *every* event, not just start/end: either data source may be the
    first to mention a session id, and the transcript poller routinely enriches a
    session (model, tokens) after it has already ended.
    """
    row = db.get(Session, event.session_id)
    if row is None:
        row = Session(
            id=event.session_id,
            start_time=event.timestamp,
            agent=event.agent,
            model=event.model,
            token_count=0,
            estimated_cost=0.0,
        )
        db.add(row)
    else:
        # SQLite hands datetimes back naive (models.py:30-31); every other read
        # path re-attaches UTC via as_utc() before using the value (see
        # api/routers/*.py). This was the one that didn't, which is why a
        # second batch for the same session raised TypeError comparing an
        # aware event.timestamp against a naive row.start_time -- silently
        # dropping every event after a session's first (review_report.md F-1).
        row.start_time = as_utc(row.start_time)
        row.end_time = as_utc(row.end_time)
        # Events can arrive out of order across the two sources, so widen the
        # window rather than assuming this event is the newest.
        if event.timestamp < row.start_time:
            row.start_time = event.timestamp

    if event.model and not row.model:
        row.model = event.model

    if event.event is EventType.SESSION_ENDED:
        if row.end_time is None or event.timestamp > row.end_time:
            row.end_time = event.timestamp
            row.duration = max((row.end_time - row.start_time).total_seconds(), 0.0)

    if event.event is EventType.RESPONSE_RECEIVED:
        tokens = event.metadata.get("token_count")
        if isinstance(tokens, int) and tokens > 0:
            row.token_count = (row.token_count or 0) + tokens
        if cost:
            row.estimated_cost = (row.estimated_cost or 0.0) + cost

    return row


def _write_derived(db: SASession, event: UniversalEvent) -> None:
    """Fan out to at most one derived table (ADR-006)."""
    if event.event in FILE_EVENT_TYPES and event.file:
        record = db.execute(
            select(FileRecord).where(
                FileRecord.session_id == event.session_id,
                FileRecord.filename == event.file,
            )
        ).scalar_one_or_none()
        if record is None:
            record = FileRecord(
                session_id=event.session_id,
                filename=event.file,
                additions=0,
                deletions=0,
                modifications=0,
            )
            db.add(record)
        if event.event is EventType.FILE_MODIFIED:
            record.modifications = (record.modifications or 0) + 1
            record.additions = (record.additions or 0) + int(
                event.metadata.get("lines_added") or 0
            )
            record.deletions = (record.deletions or 0) + int(
                event.metadata.get("lines_removed") or 0
            )
            record.last_modified = event.timestamp

    elif event.event is EventType.TERMINAL_COMMAND:
        db.add(
            Command(
                session_id=event.session_id,
                command=str(event.metadata.get("command") or ""),
                timestamp=event.timestamp,
                exit_code=event.metadata.get("exit_code"),
            )
        )

    elif event.event is EventType.PROMPT_SUBMITTED:
        # prompt_length only -- never the text (PRD section 21).
        db.add(
            Prompt(
                session_id=event.session_id,
                prompt_length=int(event.metadata.get("length") or 0),
                timestamp=event.timestamp,
            )
        )


def persist_events(events: Iterable[UniversalEvent], costs: dict[int, float] | None = None) -> int:
    """Write a batch of events in one transaction. Returns the count written."""
    costs = costs or {}
    written = 0
    with session_scope() as db:
        for index, event in enumerate(events):
            _upsert_session(db, event, cost=costs.get(index, 0.0))
            # Flush so the sessions row exists before the FK-bearing rows below.
            db.flush()
            db.add(
                Event(
                    session_id=event.session_id,
                    timestamp=event.timestamp,
                    event_type=event.event.value,
                    file=event.file,
                    metadata_=dict(event.metadata or {}),
                )
            )
            _write_derived(db, event)
            written += 1
    return written


class IngestionPipeline:
    """Owns the queue and the single writer coroutine."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter
        self._queue: asyncio.Queue[UniversalEvent | None] = asyncio.Queue(
            maxsize=QUEUE_MAX_SIZE
        )
        self._task: asyncio.Task[None] | None = None

    async def submit(self, event: UniversalEvent) -> None:
        await self._queue.put(event)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="ingestion-writer")

    async def stop(self) -> None:
        """Drain what is queued, then stop. Called from FastAPI's lifespan."""
        if self._task is None:
            return
        await self._queue.put(None)
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        finally:
            self._task = None

    async def _run(self) -> None:
        registry.register(NAME)
        while True:
            batch: list[UniversalEvent] = []
            stopping = False
            batch_failed = False

            item = await self._queue.get()
            if item is None:
                stopping = True
            else:
                batch.append(item)

            # Opportunistically drain whatever else is already queued so a
            # backfill commits in batches rather than one transaction per event.
            while len(batch) < BATCH_SIZE and not stopping:
                try:
                    item = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is None:
                    stopping = True
                else:
                    batch.append(item)

            if batch:
                costs = {
                    i: self._safe_cost(evt) for i, evt in enumerate(batch)
                }
                try:
                    await asyncio.to_thread(persist_events, batch, costs)
                except Exception as exc:  # noqa: BLE001
                    # A failed batch must not kill the writer: that would
                    # silently stop all ingestion while the app looked healthy.
                    # It must also not stay silent to /stats -- see NAME's docstring.
                    logger.exception("Failed to persist a batch of %d events", len(batch))
                    registry.mark_failure(NAME, exc)
                    batch_failed = True
                else:
                    registry.mark_success(NAME)

            if stopping:
                # stop() (FastAPI lifespan teardown) always drains with a final
                # batch attempt before returning. If that last batch is what
                # just failed, a clean "stopped" status would immediately erase
                # the "degraded" signal above -- reporting a reassuring shutdown
                # instead of the failure an operator restarting the app needs to
                # see. Leave it as "degraded" in that case.
                if not batch_failed:
                    registry.mark_stopped(NAME)
                return

    def _safe_cost(self, event: UniversalEvent) -> float:
        estimator = getattr(self._adapter, "estimate_cost", None)
        if estimator is None:
            return 0.0
        try:
            return float(estimator(event) or 0.0)
        except Exception:  # noqa: BLE001
            logger.debug("Cost estimation failed for %s", event.event.value)
            return 0.0
