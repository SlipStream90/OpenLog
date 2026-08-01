"""Event -> human-readable timeline label.

Kept server-side (api_contracts.md) so the mapping exists once rather than being
duplicated in the dashboard.

Labels describe *what happened*, never *why*. PRD section 14 is explicit that the
timeline is an observable action replay, not a reconstruction of model reasoning
-- so no label may editorialize or infer intent.
"""

from __future__ import annotations

from typing import Any

from backend.shared.events import EventType

_SIMPLE_LABELS = {
    EventType.SESSION_STARTED: "Session started",
    EventType.SESSION_ENDED: "Session finished",
    EventType.PROMPT_SUBMITTED: "Prompt submitted",
    EventType.RESPONSE_RECEIVED: "Response received",
    EventType.TEST_EXECUTED: "Tests executed",
    EventType.TEST_PASSED: "Tests passed",
    EventType.TEST_FAILED: "Tests failed",
    EventType.GIT_COMMIT: "Git commit",
    EventType.BUILD_STARTED: "Build started",
    EventType.BUILD_FINISHED: "Build finished",
}


def label_for(event_type: str, file: str | None, metadata: dict[str, Any] | None) -> str:
    """Build the timeline label for one event."""
    metadata = metadata or {}
    try:
        kind = EventType(event_type)
    except ValueError:
        # An event type not in PRD section 12 should be impossible (the adapter
        # drops unmapped payloads), but a readable fallback beats a 500.
        return event_type.replace("_", " ").capitalize()

    if kind is EventType.FILE_OPENED:
        return f"Opened {file}" if file else "Opened a file"
    if kind is EventType.FILE_MODIFIED:
        return f"Modified {file}" if file else "Modified a file"
    if kind is EventType.FILE_DELETED:
        return f"Deleted {file}" if file else "Deleted a file"
    if kind is EventType.TERMINAL_COMMAND:
        command = metadata.get("command")
        return f"Ran: {command}" if command else "Ran a command"
    if kind in (EventType.ERROR, EventType.WARNING):
        message = metadata.get("message")
        prefix = "Error" if kind is EventType.ERROR else "Warning"
        return f"{prefix}: {message}" if message else prefix

    return _SIMPLE_LABELS.get(kind, event_type.replace("_", " ").capitalize())
