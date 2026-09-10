"""ClaudeAdapter -- the only Adapter implementation this mission builds.

Implements the PRD section 18 interface (data_models.md section 5). All
Claude-specific knowledge lives here and in `event_mapper.py`; the telemetry,
database and API layers see only `UniversalEvent`.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.adapters.claude import event_mapper, pricing
from backend.shared.events import EventSource, EventType, UniversalEvent
from backend.shared.timeutil import utcnow

logger = logging.getLogger(__name__)


class ClaudeAdapter:
    """Normalizes Claude Code hook and transcript payloads.

    ## Contract note (flagged for BOND)

    `data_models.md` section 5 declares `capture_event(...) -> UniversalEvent |
    None`. That signature is implemented exactly as specified and is what the
    `Adapter` protocol checks. But one raw payload can genuinely describe more
    than one observation -- a finished `pytest` run is both a `terminal_command`
    (Commands table) and a `test_passed` (Tests metric) -- and returning only one
    of them would silently drop the other.

    So `capture_events()` (plural) is added alongside it, returning the full
    list, and the telemetry engine calls that. `capture_event()` remains and
    returns the first/primary event, so the declared contract still holds.
    This is an **addition** to the interface, not a change to it; recorded here
    rather than resolved silently (Article VI).
    """

    name = "claude"

    def __init__(self) -> None:
        self._known_sessions: set[str] = set()

    # -- Adapter protocol ---------------------------------------------------

    def initialize(self) -> None:
        """Prepare adapter state. Must succeed on a machine with no Claude Code."""
        pricing.load_pricing()
        logger.debug("ClaudeAdapter initialized (priced=%s)", pricing.is_priced())

    def start_session(
        self, session_id: str, raw: dict[str, Any], source: EventSource = "hook"
    ) -> None:
        if session_id:
            self._known_sessions.add(session_id)

    def end_session(self, session_id: str, raw: dict[str, Any] | None = None) -> None:
        self._known_sessions.discard(session_id)

    def capture_event(
        self, raw: dict[str, Any], source: EventSource = "hook"
    ) -> UniversalEvent | None:
        """Normalize one payload to its primary event, or `None` if unmapped."""
        events = self.capture_events(raw, source)
        return events[0] if events else None

    # -- Extension used by the telemetry engine -----------------------------

    def capture_events(
        self, raw: dict[str, Any], source: EventSource = "hook"
    ) -> list[UniversalEvent]:
        """Normalize one payload into every event it describes.

        Never raises: a malformed payload yields `[]` and a debug log. An
        exception escaping here would take down a watcher loop, and the brief
        requires ingestion failures to stay contained (PRD section 25).
        """
        if not isinstance(raw, dict):
            return []
        try:
            events = event_mapper.map_payload(raw, source)
        except Exception:
            logger.exception("Failed to normalize %s payload; dropping it", source)
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

    # -- Helpers ------------------------------------------------------------

    def _ensure_session_id(self, event: UniversalEvent) -> UniversalEvent:
        """Apply ADR-001's orphan fallback.

        An event with no discoverable session id is bucketed by hour rather than
        discarded -- it is still evidence something happened, and PRD user story
        3 requires unexpected input to degrade rather than vanish.
        """
        if event.session_id:
            return event

        bucket = utcnow().strftime("%Y%m%dT%H")
        synthetic = f"unmatched-{self.name}-{bucket}"
        logger.warning(
            "Event %s had no discoverable session id; bucketing under %s",
            event.event.value,
            synthetic,
        )
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
        """Cost contribution of one enrichment event. 0.0 when unpriced."""
        if event.event is not EventType.RESPONSE_RECEIVED:
            return 0.0
        meta = event.metadata or {}
        return pricing.estimate_cost(
            event.model,
            int(meta.get("input_tokens") or 0),
            int(meta.get("output_tokens") or 0),
        )
