"""Timestamp parsing shared by the adapters.

Every `UniversalEvent.timestamp` must be timezone-aware UTC (enforced in
`events.py`). Agents emit timestamps in inconsistent shapes, so parsing is
centralized here rather than repeated per adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def utcnow() -> datetime:
    """Aware UTC now. Use instead of the deprecated `datetime.utcnow()`."""
    return datetime.now(UTC)


def parse_timestamp(value: Any, *, default: datetime | None = None) -> datetime:
    """Best-effort parse of an agent-supplied timestamp into aware UTC.

    Falls back to `default` (or now) rather than raising: a missing or
    unparseable timestamp must not cost us the whole event (ADR-009).
    """
    fallback = default if default is not None else utcnow()

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        # Epoch seconds vs milliseconds: anything past ~2001 in seconds is well
        # under 1e11, so a larger magnitude means milliseconds.
        seconds = value / 1000.0 if value > 1e11 else float(value)
        try:
            parsed = datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return fallback
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        # `fromisoformat` on 3.11+ handles most ISO-8601, but not a trailing "Z".
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return fallback
    else:
        return fallback

    if parsed.tzinfo is None:
        # An agent emitting a naive timestamp means local wall-clock time.
        parsed = parsed.astimezone()
    return parsed.astimezone(UTC)
