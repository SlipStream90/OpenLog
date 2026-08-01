"""Tails the hook queue file written by `hook_handler.py`.

Own `while True: try/except` loop: an exception in one poll cycle is logged, the
watcher is marked degraded, and the loop continues. It never propagates to the
transcript poller or to the FastAPI app (PRD section 25, ARCHITECTURE.md section 5).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from backend.shared import paths
from backend.telemetry.offsets import OffsetStore
from backend.telemetry.watcher_status import registry

logger = logging.getLogger(__name__)

NAME = "hook_queue_tailer"
POLL_INTERVAL_SECONDS = 1.0
#: Backoff after a failure, so a persistent problem (e.g. unreadable file) does
#: not spin the loop at full speed writing a log line every second.
ERROR_BACKOFF_SECONDS = 15.0
MAX_BYTES_PER_CYCLE = 2_000_000


def read_new_lines(path: Path, offset: int) -> tuple[list[dict], int]:
    """Read complete JSON lines from `offset`. Returns (records, new_offset).

    Only bytes forming complete newline-terminated lines advance the offset --
    the hook handler may be mid-append, and consuming a partial line would
    corrupt every record after it.
    """
    if not path.is_file():
        return [], offset

    size = path.stat().st_size
    if size < offset:
        logger.info("Queue file %s shrank; restarting from 0", path)
        offset = 0
    if size == offset:
        return [], offset

    with path.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read(MAX_BYTES_PER_CYCLE)

    cut = chunk.rfind(b"\n")
    if cut == -1:
        return [], offset
    complete = chunk[: cut + 1]

    records: list[dict] = []
    for line in complete.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line.decode("utf-8", errors="replace"))
        except (ValueError, TypeError):
            logger.debug("Skipping malformed queue line in %s", path)
            continue
        if isinstance(record, dict):
            records.append(record)

    return records, offset + len(complete)


class QueueTailer:
    """Watcher: hook queue file -> adapter -> ingestion queue."""

    def __init__(self, adapter, pipeline, offsets: OffsetStore, path: Path | None = None):
        self._adapter = adapter
        self._pipeline = pipeline
        self._offsets = offsets
        self._path = path if path is not None else paths.hook_queue_path()

    async def run(self) -> None:
        registry.register(NAME)
        logger.info("QueueTailer watching %s", self._path)
        while True:
            try:
                await self._poll_once()
                registry.mark_success(NAME)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                registry.mark_stopped(NAME)
                raise
            except Exception as exc:  # noqa: BLE001 -- isolation is the point
                logger.exception("QueueTailer cycle failed; continuing")
                registry.mark_failure(NAME, exc)
                await asyncio.sleep(ERROR_BACKOFF_SECONDS)

    async def _poll_once(self) -> None:
        offset = self._offsets.get(self._path)
        records, new_offset = await asyncio.to_thread(
            read_new_lines, self._path, offset
        )
        for record in records:
            for event in self._adapter.capture_events(record, "hook"):
                await self._pipeline.submit(event)

        if new_offset != offset:
            self._offsets.set(self._path, new_offset)
            await asyncio.to_thread(self._offsets.save)
