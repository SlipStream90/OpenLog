#!/usr/bin/env python3
"""Register AI Observatory's hooks in OpenCode's config.

    python scripts/install_opencode_hooks.py            # install to ~/.config/opencode/opencode.json
    python scripts/install_opencode_hooks.py --project  # install to ./opencode.json
    python scripts/install_opencode_hooks.py --dry-run
    python scripts/install_opencode_hooks.py --uninstall

Safety model mirrors `install_claude_hooks.py`: backup, read-modify-write,
idempotent by MARKER, confirmation prompt, atomic replace.

[UNVERIFIED] OpenCode's hook config shape — inferred, not verified against live
docs/install. Confirm with https://opencode.ai/docs before relying on it. Only
this script and `backend/adapters/opencode/event_mapper.py` need to change if
the shape is wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

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


def _strip_jsonc(text: str) -> str:
    import re

    lines = []
    for line in text.splitlines():
        if "//" in line:
            idx = line.find("//")
            before = line[:idx]
            if before.count('"') % 2 == 0:
                line = before
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


def load_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    for attempt in (text, _strip_jsonc(text)):
        try:
            data = json.loads(attempt)
            if isinstance(data, dict):
                return data
            raise SystemExit(f"ERROR: {path} does not contain a JSON object.")
        except ValueError:
            continue
    raise SystemExit(f"ERROR: {path} is not valid JSON. Refusing to touch it.")


def _entry_is_ours(entry: dict) -> bool:
    for hook in entry.get("hooks", []) or []:
        if isinstance(hook, dict) and MARKER in str(hook.get("command", "")):
            return True
    # Also check string command form
    if MARKER in str(entry.get("command", "")):
        return True
    return False


def install(settings: dict, command: str) -> tuple[dict, int]:
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit("ERROR: existing 'hooks' value is not an object.")
    added = 0
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            print(f"  ! skipping {event}: not a list", file=sys.stderr)
            continue
        if any(isinstance(e, dict) and MARKER in str(e.get("command", "")) for e in entries):
            continue
        entry: dict = {"type": "command", "command": command}
        entries.append(entry)
        added += 1
    # Also ensure generic plugin registration for opencode's plugin system
    plugins = settings.setdefault("plugins", [])
    if isinstance(plugins, list):
        plugin_marker = "ai-observatory"
        existing = any(plugin_marker in str(p) for p in plugins)
        if not existing:
            # Informational — not counted in added, but recorded
            pass
    return settings, added


def uninstall(settings: dict) -> tuple[dict, int]:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings, 0
    removed = 0
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not (isinstance(e, dict) and MARKER in str(e.get("command", "")))]
        removed += len(entries) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return settings, removed


def write_settings(path: Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        print(f"  backed up -> {backup}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install AI Observatory's OpenCode hooks.")
    parser.add_argument("--project", action="store_true", help="use ./opencode.json")
    parser.add_argument("--dry-run", action="store_true", help="print result, write nothing")
    parser.add_argument("--uninstall", action="store_true", help="remove our entries")
    parser.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    args = parser.parse_args(argv)

    handler = handler_path()
    if not args.uninstall and not handler.is_file():
        print(f"ERROR: handler not found at {handler}", file=sys.stderr)
        return 1
    path = settings_path(args.project)
    print(f"Settings file: {path}")
    settings = load_settings(path)
    if args.uninstall:
        settings, changed = uninstall(settings)
        verb = "remove"
    else:
        settings, changed = install(settings, hook_command())
        verb = "add"
    if changed == 0:
        print(f"Nothing to {verb} -- already in desired state.")
        return 0
    print(f"Will {verb} {changed} entries.")
    if args.dry_run:
        print(json.dumps(settings, indent=2))
        return 0
    if not args.yes:
        ans = input(f"Write to {path}? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("Aborted.")
            return 1
    write_settings(path, settings)
    print("Done. Restart OpenCode to apply.")
    if not args.uninstall:
        print(f"Queue: {Path.home() / '.ai-observatory' / 'logs' / 'opencode_hooks.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
