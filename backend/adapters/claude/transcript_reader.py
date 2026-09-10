"""Locates and reads Claude Code transcript JSONL files.

Deliberately dumb: this module knows how to *find* transcripts and read new
lines from a byte offset. It does no normalization -- field-name probing and
mapping to Universal Events happen in `event_mapper.py` / `adapter.py`, so that
the [UNVERIFIED] transcript schema is interpreted in exactly one place
(ARCHITECTURE.md section 7, ADR-009).

Offsets are owned by the caller (`backend/telemetry/transcript_poller.py`),
which persists them; this module is stateless.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.shared import paths

logger = logging.getLogger(__name__)

#: Cap on bytes consumed from a single file in one poll cycle. A very large
#: backfill should be spread across cycles rather than blocking the event loop.
MAX_BYTES_PER_CYCLE = 2_000_000


@dataclass(frozen=True)
class TranscriptBatch:
    """New lines read from one transcript file, plus the resulting offset."""

    path: Path
    records: list[dict[str, Any]]
    new_offset: int


def discover_transcripts(root: Path | None = None) -> list[Path]:
    """Find every transcript file under the Claude projects directory.

    Returns an empty list (never raises) when the directory does not exist --
    a machine with no Claude Code install is a normal, supported state.
    """
    base = root if root is not None else paths.claude_transcript_root()
    try:
        if not base.is_dir():
            logger.debug("No Claude transcript directory at %s", base)
            return []
        return sorted(base.rglob("*.jsonl"))
    except OSError as exc:
        logger.warning("Could not scan transcripts at %s: %s", base, exc)
        return []


def read_new_records(path: Path, offset: int = 0) -> TranscriptBatch:
    """Read complete JSONL records from `offset` onward.

    Claude Code appends to these files while we read them, so the final line may
    be a partial write. We only advance the offset past bytes that formed a
    complete, newline-terminated line -- the partial tail is left to be re-read
    next cycle. Getting this wrong would corrupt every subsequent record in the
    file.
    """
    records: list[dict[str, Any]] = []
    try:
        size = path.stat().st_size
    except OSError as exc:
        logger.warning("Cannot stat transcript %s: %s", path, exc)
        return TranscriptBatch(path=path, records=[], new_offset=offset)

    if size < offset:
        # File shrank: rotated or replaced. Start over rather than reading from
        # a meaningless position.
        logger.info("Transcript %s shrank (%d < %d); restarting from 0", path, size, offset)
        offset = 0
    if size == offset:
        return TranscriptBatch(path=path, records=[], new_offset=offset)

    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read(MAX_BYTES_PER_CYCLE)
    except OSError as exc:
        logger.warning("Cannot read transcript %s: %s", path, exc)
        return TranscriptBatch(path=path, records=[], new_offset=offset)

    consumed = chunk.rfind(b"\n")
    if consumed == -1:
        # No complete line yet.
        return TranscriptBatch(path=path, records=[], new_offset=offset)
    complete = chunk[: consumed + 1]

    for line in complete.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line.decode("utf-8", errors="replace"))
        except (ValueError, TypeError):
            # PRD user story 3: one malformed line must not cost us the file.
            logger.debug("Skipping malformed transcript line in %s", path)
            continue
        if isinstance(record, dict):
            records.append(record)

    return TranscriptBatch(
        path=path, records=records, new_offset=offset + len(complete)
    )
