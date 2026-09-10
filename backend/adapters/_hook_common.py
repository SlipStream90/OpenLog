"""Shared hot-path logic for the four hook-handler shims. STDLIB ONLY.

Claude Code / OpenCode / Kilo Code / Codex each invoke their own
`backend/adapters/<agent>/hook_handler.py` synchronously, mid-session. Those
shims only resolve `sys.path` to this directory and call `run()` with their
queue filename -- every behavioral line lives here, so the hot path is
reviewed and fixed once.

Constraints (inherited from the shims' contract):
1. Stdlib imports only -- importing anything heavier adds startup latency to
   every tool call in the user's session.
2. No work beyond one append: read stdin, append one line, exit.
3. Never fail visibly: any exception still exits 0 with empty stderr.
   Losing one telemetry event beats interrupting a session (ADR-007).
"""

import json
import os
import sys
import time
from pathlib import Path

#: Matches `backend.shared.paths` queue locations. Kept in sync by hand; the
#: stdlib-only constraint above forbids importing it.
_ENV_HOME_OVERRIDE = "AI_OBSERVATORY_HOME"

#: Refuse to buffer an unbounded payload into memory. Hook payloads are
#: small; anything past this is malformed or hostile.
_MAX_STDIN_BYTES = 1_000_000


def queue_path(queue_relative: tuple[str, ...]) -> Path:
    override = os.environ.get(_ENV_HOME_OVERRIDE)
    root = Path(override).expanduser() if override else Path.home() / ".ai-observatory"
    return root.joinpath(*queue_relative)


def append_line(path: Path, line: str) -> None:
    """Append one line atomically enough for concurrent hook processes.

    Several hooks can fire near-simultaneously, each as its own process.
    Opening with O_APPEND and issuing a single `write()` of a payload this
    small means the kernel will not interleave two records; a
    read-modify-write or a multi-call write would.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = line.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def run(queue_relative: tuple[str, ...]) -> int:
    """Read one stdin payload, append it, return a process exit code."""
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

        # The only enrichment this hot path performs: a receipt timestamp, so
        # the tailer can order events even if the payload carries no usable time.
        payload["_received_at"] = time.time()

        append_line(queue_path(queue_relative), json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 -- ADR-007: never surface anything to the user
        return 0
    except BaseException:  # noqa: BLE001
        # Covers MemoryError/KeyboardInterrupt too. A hook must not be the
        # reason a coding session sees a traceback.
        return 0
    return 0


if __name__ == "__main__":
    # Always exit 0. A hook must never be the reason a session sees a failure.
    sys.exit(run(("logs", "ai-observatory-hooks.jsonl")))
