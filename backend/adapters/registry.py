"""Adapter registry -- the one place that names every concrete agent adapter.

`backend.telemetry` builds its default watcher set from here, and
`TranscriptPoller` resolves its default transcript reader through here, so no
watcher module hard-codes any single agent's imports. Adding a fourth agent
means adding one spec entry below -- not editing the engine.

All adapter/reader imports are lazy (`importlib` inside functions): merely
importing this registry never pulls in an adapter's modules, which keeps
`pytest --collect-only` and any partial install cheap.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any


#: Per-agent wiring. `queue` / `transcripts` name functions in
#: `backend.shared.paths`; `reader` is the transcript-reader module.
_SPECS: dict[str, dict[str, str]] = {
    "claude": {
        "adapter": "backend.adapters.claude.adapter:ClaudeAdapter",
        "reader": "backend.adapters.claude.transcript_reader",
        "queue": "hook_queue_path",
        "transcripts": "claude_transcript_root",
    },
    "opencode": {
        "adapter": "backend.adapters.opencode.adapter:OpenCodeAdapter",
        "reader": "backend.adapters.opencode.transcript_reader",
        "queue": "opencode_hook_queue_path",
        "transcripts": "opencode_transcript_root",
    },
    "kilocode": {
        "adapter": "backend.adapters.kilocode.adapter:KiloCodeAdapter",
        "reader": "backend.adapters.kilocode.transcript_reader",
        "queue": "kilocode_hook_queue_path",
        "transcripts": "kilocode_transcript_root",
    },
}


def agent_names() -> list[str]:
    """Registered agent names, in watcher build order."""
    return list(_SPECS)


def build_adapter(name: str) -> Any:
    """Instantiate the adapter for `name`. Raises KeyError for unknown agents."""
    module_path, _, class_name = _SPECS[name]["adapter"].partition(":")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def build_default_adapters() -> dict[str, Any]:
    """`{agent_name: adapter}` for every registered agent."""
    return {name: build_adapter(name) for name in agent_names()}


def reader_for(name: str):
    """The transcript-reader module for `name` (duck-typed, never imported eagerly)."""
    return importlib.import_module(_SPECS[name]["reader"])


def hook_queue_path_for(name: str) -> Path:
    """Queue file the agent's hook handler appends to."""
    from backend.shared import paths

    return getattr(paths, _SPECS[name]["queue"])()
