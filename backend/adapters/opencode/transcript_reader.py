"""Locates and reads OpenCode transcript/session JSONL files."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.shared import paths

logger = logging.getLogger(__name__)
MAX_BYTES_PER_CYCLE = 2_000_000


@dataclass(frozen=True)
class TranscriptBatch:
    path: Path
    records: list[dict[str, Any]]
    new_offset: int


def discover_transcripts(root: Path | None = None) -> list[Path]:
    base = root if root is not None else paths.opencode_transcript_root()
    try:
        if not base.is_dir():
            logger.debug("No OpenCode transcript directory at %s", base)
            return []
        return sorted(base.rglob("*.jsonl"))
    except OSError as exc:
        logger.warning("Could not scan opencode transcripts at %s: %s", base, exc)
        return []


def read_new_records(path: Path, offset: int = 0) -> TranscriptBatch:
    records: list[dict[str, Any]] = []
    try:
        size = path.stat().st_size
    except OSError as exc:
        logger.warning("Cannot stat opencode transcript %s: %s", path, exc)
        return TranscriptBatch(path=path, records=[], new_offset=offset)
    if size < offset:
        logger.info("OpenCode transcript %s shrank (%d < %d); restarting from 0", path, size, offset)
        offset = 0
    if size == offset:
        return TranscriptBatch(path=path, records=[], new_offset=offset)
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read(MAX_BYTES_PER_CYCLE)
    except OSError as exc:
        logger.warning("Cannot read opencode transcript %s: %s", path, exc)
        return TranscriptBatch(path=path, records=[], new_offset=offset)
    consumed = chunk.rfind(b"\n")
    if consumed == -1:
        return TranscriptBatch(path=path, records=[], new_offset=offset)
    complete = chunk[: consumed + 1]
    for line in complete.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line.decode("utf-8", errors="replace"))
        except (ValueError, TypeError):
            logger.debug("Skipping malformed opencode transcript line in %s", path)
            continue
        if isinstance(record, dict):
            records.append(record)
    return TranscriptBatch(path=path, records=records, new_offset=offset + len(complete))
