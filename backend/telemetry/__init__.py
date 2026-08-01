"""Telemetry engine: background watchers + single-writer ingestion.

Started and stopped by FastAPI's lifespan (ARCHITECTURE.md section 1) -- one
process, no separate daemon.

This package depends only on the `Adapter` protocol, never on a concrete
adapter's types. The one place a concrete adapter is named is
`TelemetryEngine.__init__`'s default, which is composition-root wiring rather
than a dependency of the watcher logic.
"""

from __future__ import annotations

import asyncio
import logging

from backend.telemetry.ingestion import IngestionPipeline
from backend.telemetry.offsets import OffsetStore
from backend.telemetry.queue_tailer import QueueTailer
from backend.telemetry.transcript_poller import TranscriptPoller
from backend.telemetry.watcher_status import registry

logger = logging.getLogger(__name__)


class TelemetryEngine:
    """Owns the watcher tasks and the ingestion pipeline."""

    def __init__(self, adapter=None) -> None:
        if adapter is None:
            from backend.adapters.claude import ClaudeAdapter

            adapter = ClaudeAdapter()
        self._adapter = adapter
        self._offsets = OffsetStore()
        self._pipeline = IngestionPipeline(adapter)
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Start ingestion and both watchers.

        A failure to start one watcher must not prevent the other from running,
        nor stop the API from serving -- the dashboard staying up while
        telemetry is degraded is the explicit requirement (PRD section 25).
        """
        try:
            self._adapter.initialize()
        except Exception:  # noqa: BLE001
            logger.exception("Adapter initialization failed; telemetry degraded")

        await asyncio.to_thread(self._offsets.load)
        self._pipeline.start()

        watchers = (
            ("hook_queue_tailer", QueueTailer(self._adapter, self._pipeline, self._offsets)),
            ("transcript_poller", TranscriptPoller(self._adapter, self._pipeline, self._offsets)),
        )
        for name, watcher in watchers:
            try:
                self._tasks.append(asyncio.create_task(watcher.run(), name=name))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Could not start watcher %s", name)
                registry.mark_failure(name, exc)

        logger.info("Telemetry engine started with %d watcher(s)", len(self._tasks))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()

        await self._pipeline.stop()
        await asyncio.to_thread(self._offsets.save, True)
        logger.info("Telemetry engine stopped")


__all__ = [
    "IngestionPipeline",
    "OffsetStore",
    "QueueTailer",
    "TelemetryEngine",
    "TranscriptPoller",
    "registry",
]
