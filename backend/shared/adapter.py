"""The Adapter contract -- PRD section 18, data_models.md section 5.

Adding support for a new AI coding agent must require implementing only this
protocol (PRD section 28's last success metric). Nothing in `backend/telemetry/`,
`backend/database/` or `backend/api/` may import from a concrete adapter module.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.shared.events import EventSource, UniversalEvent


@runtime_checkable
class Adapter(Protocol):
    """Normalizes one agent's raw output into Universal Events."""

    #: Short agent identifier, e.g. "claude". Persisted on Session.agent.
    name: str

    def initialize(self) -> None:
        """Prepare any adapter-local state. Must not raise on a cold machine."""
        ...

    def start_session(self, session_id: str, raw: dict[str, Any], source: EventSource) -> None:
        """Note that a session has begun. Idempotent per session_id."""
        ...

    def capture_event(self, raw: dict[str, Any], source: EventSource) -> UniversalEvent | None:
        """Normalize one raw payload.

        Returns `None` -- not an exception -- when the payload maps to no
        `EventType`. Unmapped payloads are a normal, expected outcome (agents
        emit many events this product does not model), so the caller logs at
        debug level and moves on.
        """
        ...

    def end_session(self, session_id: str, raw: dict[str, Any]) -> None:
        """Note that a session has ended."""
        ...
