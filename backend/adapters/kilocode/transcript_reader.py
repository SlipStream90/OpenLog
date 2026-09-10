"""Locates Kilo Code transcript/task files.

Kilo Code stores task histories under VS Code globalStorage.
We probe the platform-appropriate locations.
"""

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
    base = root if root is not None else paths.kilocode_transcript_root()
    try:
        if not base.is_dir():
            logger.debug("No Kilo Code storage at %s", base)
            return []
        # Kilo tasks are often stored as *.jsonl, *.json, or nested dirs
        files = []
        for pattern in ("*.jsonl", "*.json", "**/*.jsonl"):
            files.extend(base.rglob(pattern))
        # also check for typical kilocode tasks folder
        return sorted(set(files))
    except OSError as exc:
        logger.warning("Could not scan kilocode transcripts at %s: %s", base, exc)
        return []


def read_new_records(path: Path, offset: int = 0) -> TranscriptBatch:
    records: list[dict[str, Any]] = []
    try:
        size = path.stat().st_size
    except OSError as exc:
        logger.warning("Cannot stat kilocode file %s: %s", path, exc)
        return TranscriptBatch(path=path, records=[], new_offset=offset)
    if size < offset:
        logger.info("KiloCode file %s shrank; restarting from 0", path)
        offset = 0
    if size == offset:
        return TranscriptBatch(path=path, records=[], new_offset=offset)
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read(MAX_BYTES_PER_CYCLE)
    except OSError as exc:
        logger.warning("Cannot read kilocode file %s: %s", path, exc)
        return TranscriptBatch(path=path, records=[], new_offset=offset)
    # Support both JSONL and single JSON array/object files
    text = chunk.decode("utf-8", errors="replace")
    # If file is a JSON array/object, try to parse whole file
    if path.suffix == ".json" and offset == 0:
        try:
            data = json.loads(text)
            if isinstance(data, list):
                for rec in data:
                    if isinstance(rec, dict):
                        records.append(rec)
                return TranscriptBatch(path=path, records=records, new_offset=size)
            if isinstance(data, dict):
                # Some kilocode exports store {"tasks": [...]}
                if isinstance(data.get("tasks"), list):
                    for rec in data["tasks"]:
                        if isinstance(rec, dict):
                            records.append(rec)
                else:
                    records.append(data)
                return TranscriptBatch(path=path, records=records, new_offset=size)
        except (ValueError, TypeError):
            pass
        # fall through to JSONL parsing

    consumed = chunk.rfind(b"\n")
    if consumed == -1:
        # No newline — maybe single JSON object without newline
        try:
            rec = json.loads(text.strip())
            if isinstance(rec, dict):
                records.append(rec)
                return TranscriptBatch(path=path, records=records, new_offset=size)
        except (ValueError, TypeError):
            pass
        return TranscriptBatch(path=path, records=[], new_offset=offset)
    complete = chunk[: consumed + 1]
    for line in complete.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line.decode("utf-8", errors="replace"))
        except (ValueError, TypeError):
            logger.debug("Skipping malformed kilocode line in %s", path)
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return TranscriptBatch(path=path, records=records, new_offset=offset + len(complete))
