"""Persisted watcher offsets -- ADR-002.

Without this, every backend restart would either re-ingest each queue/transcript
file from byte 0 (double-counting every session aggregate) or skip forward and
lose events. A flat JSON file in the already-provisioned `cache/` directory is
enough: offsets are process-local operational state, not domain data, so they do
not belong in the database.

NOTE: this module is an addition to backlog.json's declared writes[] for T009,
which lists the four watcher modules but no home for the shared offset store.
Both watchers need identical load/save/atomic-write logic; duplicating it is how
the two files end up disagreeing about the on-disk format.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from backend.shared import paths

logger = logging.getLogger(__name__)


class OffsetStore:
    """A `{file_path: byte_offset}` map persisted to disk."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else paths.tailer_state_path()
        self._offsets: dict[str, int] = {}
        self._dirty = False

    def load(self) -> None:
        """Read offsets from disk. A missing or corrupt file means 'start fresh'."""
        try:
            if not self._path.is_file():
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._offsets = {
                    str(k): int(v) for k, v in data.items() if isinstance(v, (int, float))
                }
        except (OSError, ValueError, TypeError) as exc:
            # Restarting from 0 duplicates events, which is bad but recoverable;
            # crashing the watcher on a corrupt cache file is worse.
            logger.warning("Could not read offsets from %s: %s", self._path, exc)
            self._offsets = {}

    def get(self, key: Path | str) -> int:
        return self._offsets.get(str(key), 0)

    def set(self, key: Path | str, offset: int) -> None:
        text = str(key)
        if self._offsets.get(text) != offset:
            self._offsets[text] = offset
            self._dirty = True

    def save(self, force: bool = False) -> None:
        """Persist offsets via write-to-temp + replace.

        Atomic rename matters here: a partial write of this file, interrupted by
        a machine shutdown, would leave unparseable JSON and silently reset every
        offset to 0 on next start.
        """
        if not self._dirty and not force:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._offsets, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)
            self._dirty = False
        except OSError as exc:
            logger.warning("Could not persist offsets to %s: %s", self._path, exc)
