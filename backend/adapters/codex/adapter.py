"""CodexAdapter -- the same `Adapter` contract as the other agents.

All Codex-specific parsing stays in `event_mapper`/`transcript_reader`;
everything downstream only ever sees `UniversalEvent` (PRD section 18).
"""

from __future__ import annotations

import logging
from typing import Any

from backend.adapters.codex import event_mapper
from backend.shared.events import EventSource, EventType, UniversalEvent
from backend.shared.timeutil import utcnow

logger = logging.getLogger(__name__)


class CodexAdapter:
    name = "codex"

    def __init__(self) -> None:
        self._known_sessions: set[str] = set()

    def initialize(self) -> None:
        logger.debug("CodexAdapter initialized")

    def start_session(self, session_id: str, raw: dict[str, Any], source: EventSource = "hook") -> None:
        if session_id:
            self._known_sessions.add(session_id)

    def end_session(self, session_id: str, raw: dict[str, Any] | None = None) -> None:
        self._known_sessions.discard(session_id)

    def capture_event(self, raw: dict[str, Any], source: EventSource = "hook") -> UniversalEvent | None:
        events = self.capture_events(raw, source)
        return events[0] if events else None

    def capture_events(self, raw: dict[str, Any], source: EventSource = "hook") -> list[UniversalEvent]:
        if not isinstance(raw, dict):
            return []
        try:
            events = event_mapper.map_payload(raw, source)
        except Exception:
            logger.exception("Failed to normalize codex %s payload", source)
            return []
        resolved: list[UniversalEvent] = []
        for evt in events:
            evt = self._ensure_session_id(evt)
            if evt.event is EventType.SESSION_STARTED:
                self.start_session(evt.session_id, raw, source)
            elif evt.event is EventType.SESSION_ENDED:
                self.end_session(evt.session_id, raw)
            resolved.append(evt)
        return resolved

    def _ensure_session_id(self, event: UniversalEvent) -> UniversalEvent:
        if event.session_id:
            return event
        bucket = utcnow().strftime("%Y%m%dT%H")
        synthetic = f"unmatched-{self.name}-{bucket}"
        logger.warning("Codex event %s had no session id; bucketing under %s", event.event.value, synthetic)
        return UniversalEvent(
            session_id=synthetic,
            timestamp=event.timestamp,
            agent=event.agent,
            event=event.event,
            model=event.model,
            file=event.file,
            metadata=event.metadata,
            source=event.source,
        )

    def estimate_cost(self, event: UniversalEvent) -> float:
        # No pricing table for codex yet -- return 0. Same rationale as the
        # honest-empty shared table: a guessed dollar figure is worse than none.
        return 0.0
