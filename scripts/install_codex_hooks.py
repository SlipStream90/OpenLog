#!/usr/bin/env python3
"""Register AI Observatory's hooks in Codex CLI's config.

    python scripts/install_codex_hooks.py            # install to ~/.codex/hooks.json
    python scripts/install_codex_hooks.py --project  # install to ./.codex/hooks.json
    python scripts/install_codex_hooks.py --dry-run
    python scripts/install_codex_hooks.py --uninstall

Thin wrapper over `scripts/_hook_install_common.py` (backup, idempotency,
atomic write live there). Agent-specific surface kept here: MARKER,
HOOK_EVENTS, config locations.

[UNVERIFIED] Codex's hook config shape -- inferred, not verified against live
docs/install. Confirm before relying on it. Only this script and
`backend/adapters/codex/event_mapper.py` need to change if the shape is wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_install_common import install_entries, run_cli, uninstall_entries

MARKER = "codex.hook_handler.py"
HOOK_EVENTS = ("session_start", "session_end", "tool_before", "tool_after", "message", "stop")


def handler_path() -> Path:
    return Path(__file__).resolve().parent.parent / "backend" / "adapters" / "codex" / "hook_handler.py"


def hook_command() -> str:
    return f'"{sys.executable}" "{handler_path()}"'


def settings_path(project: bool) -> Path:
    if project:
        return Path.cwd() / ".codex" / "hooks.json"
    candidates = [
        Path.home() / ".codex" / "hooks.json",
        Path.home() / ".codex" / "config.json",
    ]
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
        description="Install AI Observatory's Codex hooks.",
        project_help="use ./.codex/hooks.json",
        settings_path=settings_path,
        handler_path=handler_path(),
        install_fn=lambda s, c: install(s, c),
        uninstall_fn=uninstall,
        queue_log=str(Path.home() / ".ai-observatory" / "logs" / "codex_hooks.jsonl"),
        restart_note="Restart Codex to apply.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
