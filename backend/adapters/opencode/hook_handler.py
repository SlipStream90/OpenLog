#!/usr/bin/env python3
"""OpenCode hook entrypoint. STDLIB ONLY.

Mirror of `backend/adapters/claude/hook_handler.py` but for OpenCode.
Constraints are identical: stdlib-only, one append, always exit 0 — never
interrupt the coding session.

OpenCode can invoke this via its hook/plugin system, e.g. in
`opencode.json`:

  {
    "hooks": {
      "session_start": "python -m backend.adapters.opencode.hook_handler",
      "tool_before": "python -m backend.adapters.opencode.hook_handler",
      "tool_after": "python -m backend.adapters.opencode.hook_handler"
    }
  }

The installer script `scripts/install_opencode_hooks.py` writes that
registration for you.
"""

import json
import os
import sys
import time
from pathlib import Path

_ENV_HOME_OVERRIDE = "AI_OBSERVATORY_HOME"
_QUEUE_RELATIVE = ("logs", "opencode_hooks.jsonl")
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
            payload = {"_unparseable": True}
        if not isinstance(payload, dict):
            payload = {"_unparseable": True}
        payload["_received_at"] = time.time()
        # Tag provenance so the tailer knows this came from opencode even if
        # the payload itself lacks an agent field.
        payload.setdefault("_agent", "opencode")
        _append_line(_queue_path(), json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001
        return 0
    except BaseException:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
