"""Telemetry engine: background watchers + single-writer ingestion.

Started and stopped by FastAPI's lifespan (ARCHITECTURE.md section 1) -- one
process, no separate daemon.

This package depends only on the `Adapter` protocol, never on a concrete
adapter's types. Concrete adapters are named in exactly one place --
`backend.adapters.registry` -- which this engine reads to build its default
watcher set.
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

    def __init__(self, adapter=None, adapters: dict[str, object] | None = None) -> None:
        # Multi-agent: if adapters map provided, use it; otherwise build the default set
        if adapters is not None:
            self._adapters = adapters
            self._adapter = adapter or next(iter(adapters.values())) if adapters else adapter
        elif adapter is not None:
            # Single adapter provided (tests) — wrap it
            self._adapters = {getattr(adapter, "name", "claude"): adapter}
            self._adapter = adapter
        else:
            from backend.adapters import registry as _registry

            self._adapters = _registry.build_default_adapters()
            self._adapter = self._adapters["claude"]
        self._offsets = OffsetStore()
        # Pipeline knows about all adapters for cost estimation
        self._pipeline = IngestionPipeline(adapters=self._adapters)
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Start ingestion and both watchers.

        A failure to start one watcher must not prevent the other from running,
        nor stop the API from serving -- the dashboard staying up while
        telemetry is degraded is the explicit requirement (PRD section 25).
        """
        # Initialize every adapter — one failing must not take down the others
        for name, ad in self._adapters.items():
            try:
                ad.initialize()  # type: ignore[attr-defined]
            except Exception:
                logger.exception("Adapter %s initialization failed; telemetry degraded", name)

        await asyncio.to_thread(self._offsets.load)
        self._pipeline.start()

        # One hook tailer + one transcript poller per registered adapter,
        # driven by the adapter registry -- adding an agent adds its watchers
        # here with no engine edits. Watcher names are stable
        # ("<agent>_hook_tailer" / "<agent>_transcript_poller") so dashboards
        # polling /stats keep working.
        from backend.adapters import registry as _registry

        watchers: list[tuple[str, object]] = []
        for agent in _registry.agent_names():
            if agent not in self._adapters:
                continue
            adapter = self._adapters[agent]
            watchers.append(
                (
                    f"{agent}_hook_tailer",
                    QueueTailer(
                        adapter,
                        self._pipeline,
                        self._offsets,
                        path=_registry.hook_queue_path_for(agent),
                        name=f"{agent}_hook_tailer",
                    ),
                )
            )
            watchers.append(
                (
                    f"{agent}_transcript_poller",
                    TranscriptPoller(
                        adapter,
                        self._pipeline,
                        self._offsets,
                        reader=_registry.reader_for(agent),
                        name=f"{agent}_transcript_poller",
                    ),
                )
            )

        for name, watcher in watchers:
            try:
                self._tasks.append(asyncio.create_task(watcher.run(), name=name))
            except Exception as exc:
                logger.exception("Could not start watcher %s", name)
                registry.mark_failure(name, exc)

        logger.info("Telemetry engine started with %d watcher(s)", len(self._tasks))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Watcher task failed during shutdown")
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
