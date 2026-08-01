"""Pydantic response models -- api_contracts.md.

These are the wire contract the dashboard codes against. Every timestamp is
serialized as an ISO-8601 UTC string with a `Z` suffix.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SessionSummary(_Base):
    """One row of the Sessions page table (PRD section 14 columns)."""

    id: str
    agent: str
    model: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    duration_seconds: float | None = None
    file_count: int = 0
    command_count: int = 0
    token_count: int = 0
    estimated_cost: float = 0.0
    #: Always null this mission. Productivity scoring is Milestone 3; the
    #: dashboard renders "N/A". Never a fabricated number (PRD.md section 4).
    productivity: float | None = None

    @field_serializer("start_time", "end_time")
    def _ser_dt(self, value: datetime | None, _info) -> str | None:
        return _iso(value)


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


class SessionDetail(SessionSummary):
    test_pass_count: int = 0
    test_fail_count: int = 0
    commit_count: int = 0


class TimelineEvent(_Base):
    timestamp: datetime
    event_type: str
    #: Human-readable label generated server-side so the event-type -> text
    #: mapping lives in one place rather than being duplicated in the dashboard.
    label: str
    file: str | None = None
    metadata: dict[str, Any] = {}

    @field_serializer("timestamp")
    def _ser_dt(self, value: datetime, _info) -> str | None:
        return _iso(value)


class TimelineResponse(BaseModel):
    session_id: str
    events: list[TimelineEvent]


class FileAggregate(_Base):
    filename: str
    session_count: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    total_modifications: int = 0
    last_modified: datetime | None = None

    @field_serializer("last_modified")
    def _ser_dt(self, value: datetime | None, _info) -> str | None:
        return _iso(value)


class FileListResponse(BaseModel):
    files: list[FileAggregate]


class WatcherStatusModel(BaseModel):
    status: str
    last_success_at: str | None = None
    last_error: str | None = None


class StatsResponse(BaseModel):
    """Today's raw aggregates. No productivity score -- deliberately absent."""

    date: str
    coding_time_seconds: float
    session_count: int
    files_changed_count: int
    estimated_cost: float
    command_count: int
    test_count: int
    #: True only when the user has supplied a pricing table. Lets the UI say
    #: "not priced" instead of implying a real $0.00. See adapters/claude/pricing.py.
    cost_is_estimated: bool = False
    #: Watcher health (ADR-004) -- satisfies PRD section 25's "notify the user in
    #: the UI" without adding a sixth endpoint the brief does not authorize.
    watchers: dict[str, WatcherStatusModel] = {}
