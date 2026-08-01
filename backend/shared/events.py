"""The Universal Event Model -- PRD section 12, data_models.md section 1.

This is the only type permitted to cross the adapter -> telemetry -> database
boundary. Agent-specific shapes (Claude Code hook payloads, transcript lines,
Codex output, ...) are normalized into `UniversalEvent` inside an adapter and
never escape it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal

EventSource = Literal["hook", "transcript"]


class EventType(str, Enum):
    """PRD section 12's supported event types, verbatim -- no additions.

    A raw agent payload that does not map to one of these is logged and dropped
    at the adapter boundary (see `backend/adapters/claude/event_mapper.py`); it
    is never forced into an approximately-correct category, because a wrong
    event type silently corrupts every downstream aggregate.
    """

    SESSION_STARTED = "session_started"
    SESSION_ENDED = "session_ended"
    PROMPT_SUBMITTED = "prompt_submitted"
    RESPONSE_RECEIVED = "response_received"
    FILE_OPENED = "file_opened"
    FILE_MODIFIED = "file_modified"
    FILE_DELETED = "file_deleted"
    TERMINAL_COMMAND = "terminal_command"
    TEST_EXECUTED = "test_executed"
    TEST_PASSED = "test_passed"
    TEST_FAILED = "test_failed"
    GIT_COMMIT = "git_commit"
    ERROR = "error"
    WARNING = "warning"
    BUILD_STARTED = "build_started"
    BUILD_FINISHED = "build_finished"


#: Event types that additionally upsert a `files` row (data_models.md section 3).
FILE_EVENT_TYPES = frozenset(
    {EventType.FILE_OPENED, EventType.FILE_MODIFIED, EventType.FILE_DELETED}
)

#: Event types counted as "tests" by GET /stats.
TEST_EVENT_TYPES = frozenset(
    {EventType.TEST_EXECUTED, EventType.TEST_PASSED, EventType.TEST_FAILED}
)


@dataclass(frozen=True)
class UniversalEvent:
    """One normalized, agent-agnostic observation.

    Frozen because an event is a historical fact: once an adapter has emitted
    it, no downstream layer may mutate it. Enrichment (e.g. a transcript
    supplying the model name after the fact) happens by emitting a *new* event,
    not by editing an existing one.
    """

    session_id: str
    timestamp: datetime
    agent: str
    event: EventType
    model: str | None = None
    file: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Provenance. Used for reconciliation/debugging only -- deliberately not
    #: part of PRD section 12's persisted schema, and the dashboard must not
    #: rely on it.
    source: EventSource = "hook"

    def __post_init__(self) -> None:
        # A naive datetime silently compares/sorts wrong against aware ones, and
        # the timeline endpoint orders strictly by timestamp. Normalize here, at
        # the one place every event must pass through, rather than trusting each
        # adapter to remember.
        if self.timestamp.tzinfo is None:
            raise ValueError(
                "UniversalEvent.timestamp must be timezone-aware (UTC). "
                "Adapters should use backend.shared.timeutil.parse_timestamp."
            )
