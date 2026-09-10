"""Tails the hook queue file written by `hook_handler.py`.

Own `while True: try/except` loop: an exception in one poll cycle is logged, the
watcher is marked degraded, and the loop continues. It never propagates to the
transcript poller or to the FastAPI app (PRD section 25, ARCHITECTURE.md section 5).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
#: Drop the ingested prefix once the processed offset passes this size. Queue
#: files hold *raw* hook payloads (prompt text, edit content), so bounding
#: their size is a privacy measure as well as a disk one: the DB keeps only
#: lengths/counts, and the queue must not become a permanent PII archive.
COMPACT_THRESHOLD_BYTES = 2_000_000


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


def compact_processed_prefix(
    path: Path, offset: int, threshold: int = COMPACT_THRESHOLD_BYTES
) -> int:
    """Drop already-ingested bytes from the head of the queue file.

    Returns the new valid offset (`0` after a compaction, else `offset`
    unchanged). Skips unless the file is big enough *and* stable: the hook
    handler appends concurrently, so if the file grew between the size check
    and the tail read, the compaction is deferred to a later cycle rather
    than risk dropping a freshly-appended line.
    """
    if offset < threshold:
        return offset
    try:
        size = path.stat().st_size
    except OSError:
        return offset
    if size < offset:
        # Shrunk (rotated externally); read_new_lines restarts from 0 itself.
        return offset
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            tail = handle.read()
        if path.stat().st_size != size:
            return offset
        tmp = path.with_name(path.name + ".compact.tmp")
        with tmp.open("wb") as handle:
            handle.write(tail)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("Could not compact queue file %s: %s", path, exc)
        return offset
    logger.info("Compacted queue file %s, reclaimed %d bytes", path, offset)
    return 0


class QueueTailer:
    """Watcher: hook queue file -> adapter -> ingestion queue."""

    def __init__(self, adapter, pipeline, offsets: OffsetStore, path: Path | None = None, name: str | None = None):
        self._adapter = adapter
        self._pipeline = pipeline
        self._offsets = offsets
        self._path = path if path is not None else paths.hook_queue_path()
        self._name = name or NAME

    async def run(self) -> None:
        registry.register(self._name)
        logger.info("QueueTailer %s watching %s", self._name, self._path)
        while True:
            try:
                await self._poll_once()
                registry.mark_success(self._name)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                registry.mark_stopped(self._name)
                raise
            except Exception as exc:
                logger.exception("QueueTailer %s cycle failed; continuing", self._name)
                registry.mark_failure(self._name, exc)
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

        compacted = await asyncio.to_thread(
            compact_processed_prefix, self._path, new_offset
        )
        if compacted != new_offset:
            self._offsets.set(self._path, compacted)
            await asyncio.to_thread(self._offsets.save)
