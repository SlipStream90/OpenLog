#!/usr/bin/env python3
"""Claude Code hook entrypoint. STDLIB ONLY -- see the constraint block below.

Claude Code invokes this script synchronously, as a subprocess, on every hook
event, while the developer is mid-session. That places three hard constraints on
this file (MISSION_BRIEF.md lines 25-29, ARCHITECTURE.md section 2, ADR-007):

1. **Stdlib imports only.** Importing SQLAlchemy/FastAPI here would add hundreds
   of milliseconds of interpreter startup to every single tool call. Nothing in
   this file may import from `backend.*` -- which is why the queue path is
   re-derived here instead of imported from `backend.shared.paths`. That
   duplication is deliberate and is the only one in the codebase.
2. **No work beyond one append.** No DB writes, no network, no parsing beyond
   `json.loads`. Read stdin, append one line, exit.
3. **Never fail visibly.** The entire body is wrapped so that any exception
   still results in exit code 0 and an empty stderr. Losing one telemetry event
   is strictly preferable to interrupting the user's coding session; that
   priority ordering comes from the brief itself.
"""

import json
import os
import sys
import time
from pathlib import Path

#: Matches `backend.shared.paths.hook_queue_path()`. Kept in sync by hand; the
#: stdlib-only constraint above forbids importing it.
_ENV_HOME_OVERRIDE = "AI_OBSERVATORY_HOME"
_QUEUE_RELATIVE = ("logs", "claude_hooks.jsonl")

#: Refuse to buffer an unbounded payload into memory. Claude Code hook payloads
#: are small; anything past this is malformed or hostile, and the queue file is
#: something the user's disk has to hold.
_MAX_STDIN_BYTES = 1_000_000


def _queue_path() -> Path:
    override = os.environ.get(_ENV_HOME_OVERRIDE)
    root = Path(override).expanduser() if override else Path.home() / ".ai-observatory"
    return root.joinpath(*_QUEUE_RELATIVE)


def _append_line(path: Path, line: str) -> None:
    """Append one line atomically enough for concurrent hook processes.

    Several Claude Code hooks can fire near-simultaneously, each as its own
    process. Opening with O_APPEND and issuing a single `write()` of a payload
    this small means the kernel will not interleave two records; a
    read-modify-write or a multi-call write would.
    """
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
            # Unparseable stdin still tells us *something* happened. Record it
            # as an envelope the tailer can skip, rather than dropping it
            # silently -- but never echo the raw bytes back, which could put
            # source code or secrets into the queue file.
            payload = {"_unparseable": True}

        if not isinstance(payload, dict):
            payload = {"_unparseable": True}

        # The only enrichment this hot path performs: a receipt timestamp, so the
        # tailer can order events even if the payload carries no usable time.
        payload["_received_at"] = time.time()

        _append_line(_queue_path(), json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 -- ADR-007: never surface anything to the user
        return 0
    except BaseException:  # noqa: BLE001
        # Covers MemoryError/KeyboardInterrupt too. A hook must not be the reason
        # a coding session sees a traceback.
        return 0
    return 0


if __name__ == "__main__":
    # Always exit 0. Claude Code may treat a non-zero hook exit as a blocking
    # failure [UNVERIFIED exact behavior -- ADR-007], and the brief forbids any
    # user-visible interruption.
    sys.exit(main())
