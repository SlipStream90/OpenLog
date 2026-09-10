#!/usr/bin/env python3
"""Codex CLI hook entrypoint. STDLIB ONLY.

Same hot-path contract as the other adapters' hook handlers: Codex invokes
this script synchronously while the developer is mid-session, so it reads
stdin, appends one line to the queue file, and always exits 0. No DB writes,
no network, no `backend.*` imports (which would add interpreter startup to
every tool call). Losing one event beats interrupting a session (ADR-007).
"""

import json
import os
import sys
import time
from pathlib import Path

#: Matches `backend.shared.paths.codex_hook_queue_path()`. Kept in sync by
#: hand; the stdlib-only constraint above forbids importing it.
_ENV_HOME_OVERRIDE = "AI_OBSERVATORY_HOME"
_QUEUE_RELATIVE = ("logs", "codex_hooks.jsonl")

#: Refuse to buffer an unbounded payload into memory.
_MAX_STDIN_BYTES = 1_000_000


def _queue_path() -> Path:
    override = os.environ.get(_ENV_HOME_OVERRIDE)
    root = Path(override).expanduser() if override else Path.home() / ".ai-observatory"
    return root.joinpath(*_QUEUE_RELATIVE)


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = line.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def main() -> int:
    try:
        raw = sys.stdin.read(_MAX_STDIN_BYTES)
        if not raw or not raw.strip():
            return 0

        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            # Never echo raw bytes back (could hold source or secrets).
            payload = {"_unparseable": True}

        if not isinstance(payload, dict):
            payload = {"_unparseable": True}

        payload["_received_at"] = time.time()

        _append_line(_queue_path(), json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 -- ADR-007: never surface anything to the user
        return 0
    except BaseException:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
