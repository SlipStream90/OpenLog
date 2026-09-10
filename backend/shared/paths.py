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


def opencode_hook_queue_path() -> Path:
    """Queue file for OpenCode hooks."""
    override = os.environ.get("OPENCODE_HOOK_QUEUE")
    if override:
        return Path(override).expanduser()
    return logs_dir() / "opencode_hooks.jsonl"


def kilocode_hook_queue_path() -> Path:
    """Queue file for Kilo Code hooks."""
    override = os.environ.get("KILOCODE_HOOK_QUEUE")
    if override:
        return Path(override).expanduser()
    return logs_dir() / "kilocode_hooks.jsonl"


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


def opencode_transcript_root() -> Path:
    """Where OpenCode writes session JSONL.

    Override with OPENCODE_TRANSCRIPT_ROOT for tests or custom installs.
    """
    override = os.environ.get("OPENCODE_TRANSCRIPT_ROOT")
    if override:
        return Path(override).expanduser()
    # Opencode default locations — probe several plausible dirs, the reader
    # will simply return empty if they don't exist.
    for cand in (
        Path.home() / ".local" / "share" / "opencode",
        Path.home() / ".opencode",
        Path.home() / ".config" / "opencode",
    ):
        if cand.is_dir():
            return cand
    return Path.home() / ".local" / "share" / "opencode"


def kilocode_transcript_root() -> Path:
    """Where Kilo Code stores task files (VS Code globalStorage)."""
    override = os.environ.get("KILOCODE_TRANSCRIPT_ROOT")
    if override:
        return Path(override).expanduser()
    # Platform-dependent VS Code storage
    candidates = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidates.append(Path(appdata) / "Code" / "User" / "globalStorage" / "kilocode.kilo-code")
        # also check Roaming/Code check via home
        candidates.append(Path.home() / "AppData" / "Roaming" / "Code" / "User" / "globalStorage" / "kilocode.kilo-code")
    else:
        candidates.append(Path.home() / ".config" / "Code" / "User" / "globalStorage" / "kilocode.kilo-code")
        candidates.append(Path.home() / ".vscode" / "globalStorage" / "kilocode.kilo-code")
    for cand in candidates:
        if cand.is_dir():
            return cand
    # Fallback — first candidate even if doesn't exist (polling will just be no-op)
    return candidates[0] if candidates else Path.home() / ".config" / "Code" / "User" / "globalStorage" / "kilocode.kilo-code"


def all_hook_queue_paths() -> list[Path]:
    """All known queue files — used by telemetry to watch every agent."""
    return [hook_queue_path(), opencode_hook_queue_path(), kilocode_hook_queue_path()]


def ensure_directories() -> None:
    """Create the local storage tree if missing. Safe to call repeatedly.

    Note: `settings.json` (PRD section 11) is deliberately NOT created -- this
    mission has no app-level settings UI, so there would be nothing to load
    (ARCHITECTURE.md section 8).
    """
    for path in (root(), sessions_dir(), analytics_dir(), logs_dir(), cache_dir()):
        path.mkdir(parents=True, exist_ok=True)
