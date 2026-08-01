"""Canonical local storage locations -- PRD section 11.

Kept in one module so the hook handler, the telemetry watchers, the database
layer and the installer script cannot drift apart on where things live.

`AI_OBSERVATORY_HOME` overrides the root; the test suite relies on this to keep
temp databases out of the developer's real `~/.ai-observatory/`.

NOTE: this module is an addition beyond the paths declared in backlog.json's
writes[] for T001/T004. It exists because five separate modules need the same
directory layout and duplicating `Path.home() / ".ai-observatory"` across them
is exactly how a queue file ends up written to one place and read from another.
`hook_handler.py` deliberately does NOT import it (stdlib-only constraint) and
re-derives the queue path itself -- the one accepted duplication, flagged in
that file.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_HOME_OVERRIDE = "AI_OBSERVATORY_HOME"


def root() -> Path:
    """Root of the local data directory (`~/.ai-observatory` by default)."""
    override = os.environ.get(ENV_HOME_OVERRIDE)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ai-observatory"


def database_path() -> Path:
    return root() / "database.sqlite"


def logs_dir() -> Path:
    return root() / "logs"


def cache_dir() -> Path:
    return root() / "cache"


def sessions_dir() -> Path:
    return root() / "sessions"


def analytics_dir() -> Path:
    return root() / "analytics"


def hook_queue_path() -> Path:
    """The append-only queue file `hook_handler.py` writes and QueueTailer reads."""
    return logs_dir() / "claude_hooks.jsonl"


def tailer_state_path() -> Path:
    """Persisted `{file_path: byte_offset}` map (ADR-002)."""
    return cache_dir() / "tailer_state.json"


def claude_transcript_root() -> Path:
    """Where Claude Code writes its own transcripts.

    [UNVERIFIED] Per MISSION_BRIEF.md line 31 (`~/.claude/projects/**/*.jsonl`).
    Not confirmed against a live install -- see the degradation note in the
    final report. Overridable for tests via CLAUDE_TRANSCRIPT_ROOT.
    """
    override = os.environ.get("CLAUDE_TRANSCRIPT_ROOT")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "projects"


def ensure_directories() -> None:
    """Create the local storage tree if missing. Safe to call repeatedly.

    Note: `settings.json` (PRD section 11) is deliberately NOT created -- this
    mission has no app-level settings UI, so there would be nothing to load
    (ARCHITECTURE.md section 8).
    """
    for path in (root(), sessions_dir(), analytics_dir(), logs_dir(), cache_dir()):
        path.mkdir(parents=True, exist_ok=True)
