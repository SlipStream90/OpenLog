#!/usr/bin/env python3
"""Register AI Observatory's hook for Kilo Code.

Kilo Code is a VS Code extension (`kilocode.kilo-code`). VS Code stores
settings in:

  Windows: %APPDATA%\\Code\\User\\settings.json
  macOS:   ~/Library/Application Support/Code/User/settings.json
  Linux:   ~/.config/Code/User/settings.json

This script adds an entry under `kilocode.hooks` (and a generic
`aiObservatory.hookCommand` key as a fallback) so the extension can invoke
`backend/adapters/kilocode/hook_handler.py` after tool calls. The exact key is
[UNVERIFIED].

    python scripts/install_kilocode_hooks.py            # install to VS Code User settings
    python scripts/install_kilocode_hooks.py --project  # install to ./.vscode/settings.json
    python scripts/install_kilocode_hooks.py --dry-run
    python scripts/install_kilocode_hooks.py --uninstall

Shared safety core (JSONC load, backup, atomic write, CLI flow) lives in
`scripts/_hook_install_common.py`. Kilo-specific surface kept here: VS Code
settings locations and the dotted-key entry shape.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_install_common import run_cli

MARKER = "kilocode.hook_handler.py"


def handler_path() -> Path:
    return Path(__file__).resolve().parent.parent / "backend" / "adapters" / "kilocode" / "hook_handler.py"


def hook_command() -> str:
    return f'"{sys.executable}" "{handler_path()}"'


def default_user_settings_path() -> Path:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "Code" / "User" / "settings.json"
        return Path.home() / "AppData" / "Roaming" / "Code" / "User" / "settings.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json"
    return Path.home() / ".config" / "Code" / "User" / "settings.json"


def settings_path(project: bool) -> Path:
    if project:
        return Path.cwd() / ".vscode" / "settings.json"
    return default_user_settings_path()


def _contains_marker(lst) -> bool:
    return any(MARKER in str(e) for e in lst)


def install(settings: dict, command: str) -> tuple[dict, int]:
    # Primary: kilocode.hooks array; VS Code settings keys may be dotted, or
    # live under a "kilocode" object -- accept all plausible locations.
    kilocode_obj = settings.get("kilocode")
    candidates = []
    if isinstance(kilocode_obj, dict):
        candidates.append(kilocode_obj.setdefault("hooks", []))
    if "kilocode.hooks" in settings and isinstance(settings["kilocode.hooks"], list):
        candidates.append(settings["kilocode.hooks"])
    if not candidates:
        # No candidate yet -- create the dotted key as primary. (Do not mirror
        # the same list into object form: aliasing one list under two keys
        # double-counts on uninstall. Uninstall still cleans every location.)
        candidates.append(settings.setdefault("kilocode.hooks", []))

    added = 0
    for lst in candidates:
        if not isinstance(lst, list):
            raise SystemExit("ERROR: existing hooks value is not a list.")
        if not _contains_marker(lst):
            lst.append({"command": command, "events": ["toolAfter", "taskComplete"]})
            added += 1
            break
    return settings, added


def uninstall(settings: dict) -> tuple[dict, int]:
    removed = 0
    for key in ["kilocode.hooks", "aiObservatory.kilocodeHook"]:
        lst = settings.get(key)
        if isinstance(lst, list):
            kept = [e for e in lst if MARKER not in str(e)]
            removed += len(lst) - len(kept)
            if kept:
                settings[key] = kept
            else:
                settings.pop(key, None)
    kilocode_obj = settings.get("kilocode")
    if isinstance(kilocode_obj, dict) and isinstance(kilocode_obj.get("hooks"), list):
        lst = kilocode_obj["hooks"]
        kept = [e for e in lst if MARKER not in str(e)]
        removed += len(lst) - len(kept)
        if kept:
            kilocode_obj["hooks"] = kept
        else:
            kilocode_obj.pop("hooks", None)
            if not kilocode_obj:
                settings.pop("kilocode", None)
    return settings, removed


def main(argv: list[str] | None = None) -> int:
    return run_cli(
        argv,
        description="Install Kilo Code hook.",
        project_help="use ./.vscode/settings.json",
        settings_path=settings_path,
        handler_path=handler_path(),
        install_fn=install,
        uninstall_fn=uninstall,
        queue_log=str(Path.home() / ".ai-observatory" / "logs" / "kilocode_hooks.jsonl"),
        restart_note="Reload VS Code to apply.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
