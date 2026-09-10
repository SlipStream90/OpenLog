"""Polls Claude Code transcripts to backfill what hooks do not expose.

Hooks give real-time actions; transcripts give model name and token counts
(MISSION_BRIEF.md line 31). This watcher is failure-isolated from the queue
tailer: a broken transcript directory degrades only this watcher, and the rest
of the pipeline keeps running (PRD section 25).
"""

from __future__ import annotations

import asyncio
import logging

from backend.telemetry.offsets import OffsetStore
from backend.telemetry.watcher_status import registry

logger = logging.getLogger(__name__)

NAME = "transcript_poller"
#: Slower than the queue tailer: transcript data is enrichment, not the
#: real-time path, and rglob over the projects tree is comparatively expensive.
#: Keeping this interval modest matters for PRD section 26's idle-footprint target.
POLL_INTERVAL_SECONDS = 5.0
ERROR_BACKOFF_SECONDS = 30.0


class TranscriptPoller:
    """Watcher: transcript JSONL -> adapter -> ingestion queue."""

    def __init__(self, adapter, pipeline, offsets: OffsetStore, reader=None, name: str | None = None):
        self._adapter = adapter
        self._pipeline = pipeline
        self._offsets = offsets
        if reader is None:
            # Resolve the default reader through the adapter registry so this
            # module never hard-codes one agent's imports. Explicit injection
            # (as the engine does) always wins.
            from backend.adapters import registry as _registry

            reader = _registry.reader_for(getattr(adapter, "name", "claude"))

        self._reader = reader
        self._name = name or NAME

    async def run(self) -> None:
        registry.register(self._name)
        while True:
            try:
                await self._poll_once()
                registry.mark_success(self._name)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                registry.mark_stopped(self._name)
                raise
            except Exception as exc:
                logger.exception("TranscriptPoller %s cycle failed; continuing", self._name)
                registry.mark_failure(self._name, exc)
                await asyncio.sleep(ERROR_BACKOFF_SECONDS)

    async def _poll_once(self) -> None:
        transcripts = await asyncio.to_thread(self._reader.discover_transcripts)
        if not transcripts:
            return

        changed = False
        for path in transcripts:
            try:
                offset = self._offsets.get(path)
                batch = await asyncio.to_thread(
                    self._reader.read_new_records, path, offset
                )
            except Exception:
                # One unreadable file must not abort the whole cycle -- the other
                # sessions' transcripts are still fine (PRD user story 3).
                logger.warning("Skipping transcript %s this cycle", path, exc_info=True)
                continue

            for record in batch.records:
                for event in self._adapter.capture_events(record, "transcript"):
                    await self._pipeline.submit(event)

            if batch.new_offset != offset:
                self._offsets.set(path, batch.new_offset)
                changed = True

        if changed:
            await asyncio.to_thread(self._offsets.save)
