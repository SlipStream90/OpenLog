#!/usr/bin/env python3
"""Register AI Observatory's hooks in OpenCode's config.

    python scripts/install_opencode_hooks.py            # install to ~/.config/opencode/opencode.json
    python scripts/install_opencode_hooks.py --project  # install to ./opencode.json
    python scripts/install_opencode_hooks.py --dry-run
    python scripts/install_opencode_hooks.py --uninstall

Thin wrapper over `scripts/_hook_install_common.py` (backup, idempotency,
atomic write live there). Agent-specific surface kept here: MARKER,
HOOK_EVENTS, config locations.

[UNVERIFIED] OpenCode's hook config shape -- inferred, not verified against live
docs/install. Confirm with https://opencode.ai/docs before relying on it. Only
this script and `backend/adapters/opencode/event_mapper.py` need to change if
the shape is wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_install_common import install_entries, run_cli, uninstall_entries

MARKER = "opencode.hook_handler.py"
# OpenCode event vocabulary — broad to match whatever the real names turn out to be
HOOK_EVENTS = ("session_start", "session_end", "tool_before", "tool_after", "chat_message", "stop")


def handler_path() -> Path:
    return Path(__file__).resolve().parent.parent / "backend" / "adapters" / "opencode" / "hook_handler.py"


def hook_command() -> str:
    return f'"{sys.executable}" "{handler_path()}"'


def settings_path(project: bool) -> Path:
    if project:
        return Path.cwd() / "opencode.json"
    # Try common locations; default to XDG
    candidates = [
        Path.home() / ".config" / "opencode" / "opencode.json",
        Path.home() / ".config" / "opencode" / "config.json",
        Path.home() / ".opencode" / "opencode.json",
    ]
    # If any already exists, use it
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def install(settings: dict, command: str) -> tuple[dict, int]:
    return install_entries(settings, command, MARKER, HOOK_EVENTS)


def uninstall(settings: dict) -> tuple[dict, int]:
    return uninstall_entries(settings, MARKER)


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        argv,
        description="Install AI Observatory's OpenCode hooks.",
        project_help="use ./opencode.json",
        settings_path=settings_path,
        handler_path=handler_path(),
        install_fn=lambda s, c: install(s, c),
        uninstall_fn=uninstall,
        queue_log=str(Path.home() / ".ai-observatory" / "logs" / "opencode_hooks.jsonl"),
        restart_note="Restart OpenCode to apply.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
