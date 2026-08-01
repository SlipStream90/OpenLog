"""Database layer round-trip tests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.database.models import Command, Event, FileRecord, Prompt, Session
from backend.database.session import session_scope
from backend.shared.events import EventType, UniversalEvent
from backend.shared.timeutil import utcnow
from backend.telemetry.ingestion import persist_events


def _event(session_id="s1", event=EventType.FILE_MODIFIED, **kwargs):
    defaults = dict(
        session_id=session_id,
        timestamp=utcnow(),
        agent="claude",
        event=event,
        file="backend/app.py",
        metadata={"lines_added": 10, "lines_removed": 3},
        source="hook",
    )
    defaults.update(kwargs)
    return UniversalEvent(**defaults)


def test_tables_are_created(temp_home):
    assert (temp_home / "database.sqlite").is_file()
    for directory in ("sessions", "analytics", "logs", "cache"):
        assert (temp_home / directory).is_dir()


def test_statistics_table_is_absent():
    """Milestone 3 scope -- must not have crept in."""
    from backend.database.models import Base

    assert "statistics" not in Base.metadata.tables


def test_insert_and_query_round_trip():
    persist_events([_event()])

    with session_scope() as db:
        session = db.get(Session, "s1")
        assert session is not None
        assert session.agent == "claude"

        events = db.execute(select(Event)).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == EventType.FILE_MODIFIED.value
        assert events[0].metadata_["lines_added"] == 10


def test_session_is_upserted_on_every_event():
    """ADR-006: any event may be the first or the last to mention a session."""
    start = utcnow()
    persist_events(
        [
            _event(event=EventType.SESSION_STARTED, timestamp=start, file=None, metadata={}),
            _event(timestamp=start + timedelta(minutes=5)),
            _event(
                event=EventType.SESSION_ENDED,
                timestamp=start + timedelta(minutes=30),
                file=None,
                metadata={},
            ),
        ]
    )

    with session_scope() as db:
        session = db.get(Session, "s1")
        assert session is not None
        assert session.end_time is not None
        assert session.duration == pytest.approx(1800, abs=1)
        assert len(db.execute(select(Event)).scalars().all()) == 3


def test_out_of_order_events_widen_the_session_window():
    """Two independent sources mean events can arrive oldest-last."""
    later = utcnow()
    earlier = later - timedelta(minutes=20)

    persist_events([_event(timestamp=later)])
    persist_events([_event(timestamp=earlier)])

    with session_scope() as db:
        session = db.get(Session, "s1")
        assert session.start_time.replace(tzinfo=None) == earlier.replace(tzinfo=None)


def test_file_records_accumulate_per_session_and_filename():
    persist_events([_event(), _event(), _event(file="backend/other.py")])

    with session_scope() as db:
        records = db.execute(select(FileRecord).order_by(FileRecord.filename)).scalars().all()
        assert len(records) == 2  # upserted, not duplicated
        app = next(r for r in records if r.filename == "backend/app.py")
        assert app.modifications == 2
        assert app.additions == 20
        assert app.deletions == 6


def test_files_unique_constraint_is_enforced():
    persist_events([_event()])
    with pytest.raises(IntegrityError):
        with session_scope() as db:
            db.add(FileRecord(session_id="s1", filename="backend/app.py"))


def test_terminal_command_writes_commands_row():
    persist_events(
        [
            _event(
                event=EventType.TERMINAL_COMMAND,
                file=None,
                metadata={"command": "pytest -q", "exit_code": 0},
            )
        ]
    )

    with session_scope() as db:
        command = db.execute(select(Command)).scalar_one()
        assert command.command == "pytest -q"
        assert command.exit_code == 0


def test_prompt_row_stores_length_only():
    persist_events(
        [_event(event=EventType.PROMPT_SUBMITTED, file=None, metadata={"length": 128})]
    )

    with session_scope() as db:
        prompt = db.execute(select(Prompt)).scalar_one()
        assert prompt.prompt_length == 128
        # The privacy guarantee, asserted at the schema level.
        assert not hasattr(prompt, "text")
        assert "text" not in Prompt.__table__.columns


def test_response_received_accumulates_tokens():
    persist_events(
        [
            _event(
                event=EventType.RESPONSE_RECEIVED,
                file=None,
                model="claude-sonnet-4-5",
                metadata={"token_count": 500},
                source="transcript",
            ),
            _event(
                event=EventType.RESPONSE_RECEIVED,
                file=None,
                metadata={"token_count": 250},
                source="transcript",
            ),
        ]
    )

    with session_scope() as db:
        session = db.get(Session, "s1")
        assert session.token_count == 750
        assert session.model == "claude-sonnet-4-5"


def test_naive_timestamps_are_rejected_at_the_boundary():
    """A naive datetime would sort wrong on the timeline; fail loudly instead."""
    from datetime import datetime

    with pytest.raises(ValueError):
        UniversalEvent(
            session_id="s1",
            timestamp=datetime(2026, 1, 15, 10, 0, 0),
            agent="claude",
            event=EventType.SESSION_STARTED,
        )
