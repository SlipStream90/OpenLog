"""Polls Claude Code transcripts to backfill what hooks do not expose.

Hooks give real-time actions; transcripts give model name and token counts
(MISSION_BRIEF.md line 31). This watcher is failure-isolated from the queue
tailer: a broken transcript directory degrades only this watcher, and the rest
of the pipeline keeps running (PRD section 25).
"""

from __future__ import annotations

import asyncio
import logging

from backend.adapters.claude import transcript_reader
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

    def __init__(self, adapter, pipeline, offsets: OffsetStore):
        self._adapter = adapter
        self._pipeline = pipeline
        self._offsets = offsets

    async def run(self) -> None:
        registry.register(NAME)
        while True:
            try:
                await self._poll_once()
                registry.mark_success(NAME)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                registry.mark_stopped(NAME)
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("TranscriptPoller cycle failed; continuing")
                registry.mark_failure(NAME, exc)
                await asyncio.sleep(ERROR_BACKOFF_SECONDS)

    async def _poll_once(self) -> None:
        transcripts = await asyncio.to_thread(transcript_reader.discover_transcripts)
        if not transcripts:
            return

        changed = False
        for path in transcripts:
            try:
                offset = self._offsets.get(path)
                batch = await asyncio.to_thread(
                    transcript_reader.read_new_records, path, offset
                )
            except Exception:  # noqa: BLE001
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
