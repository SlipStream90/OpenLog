"""In-process health registry for the background watchers.

PRD section 25 requires that a telemetry failure disable only the affected
adapter and *notify the user in the UI*. ADR-004 satisfies the notification half
by folding this registry into the existing `GET /stats` response rather than
adding a sixth endpoint (the brief fixes the API surface at five).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from backend.shared.timeutil import utcnow

WatcherState = Literal["starting", "running", "degraded", "stopped"]


@dataclass
class WatcherHealth:
    name: str
    status: WatcherState = "starting"
    last_success_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "last_success_at": (
                self.last_success_at.isoformat().replace("+00:00", "Z")
                if self.last_success_at
                else None
            ),
            "last_error": self.last_error,
        }


class WatcherRegistry:
    """Thread-safe registry of watcher health.

    Locked because the watchers write to it from the event loop while FastAPI
    serves `/stats` from a threadpool worker.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._watchers: dict[str, WatcherHealth] = {}

    def register(self, name: str) -> WatcherHealth:
        with self._lock:
            health = self._watchers.setdefault(name, WatcherHealth(name=name))
            health.status = "starting"
            return health

    def mark_success(self, name: str) -> None:
        with self._lock:
            health = self._watchers.setdefault(name, WatcherHealth(name=name))
            health.status = "running"
            health.last_success_at = utcnow()
            health.last_error = None
            health.consecutive_failures = 0

    def mark_failure(self, name: str, error: BaseException | str) -> None:
        with self._lock:
            health = self._watchers.setdefault(name, WatcherHealth(name=name))
            health.status = "degraded"
            # Store the exception's type and message, never a full traceback:
            # tracebacks can embed source lines, and this string is served over
            # HTTP to the dashboard (PRD section 21).
            health.last_error = (
                error if isinstance(error, str) else f"{type(error).__name__}: {error}"
            )
            health.consecutive_failures += 1

    def mark_stopped(self, name: str) -> None:
        with self._lock:
            health = self._watchers.setdefault(name, WatcherHealth(name=name))
            health.status = "stopped"

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: health.to_dict() for name, health in self._watchers.items()}

    def clear(self) -> None:
        with self._lock:
            self._watchers.clear()


#: Process-wide registry. Single-process app (ARCHITECTURE.md section 1), so a
#: module-level instance is the whole story.
registry = WatcherRegistry()
