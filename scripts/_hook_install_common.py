"""Shared core for the JSON-shape hook installers (opencode/kilocode/codex).

These three agents share one config shape -- `{hooks: {event: [{type,
command}]}}` with JSONC tolerance -- while Claude's `settings.json` uses a
different entry shape (`{hooks, matcher}`) and stays in
`install_claude_hooks.py`. Each thin installer keeps its own MARKER,
HOOK_EVENTS, paths and CLI text, and delegates everything else here, so a
safety fix (backup, atomic write, idempotency) lands once for all three.

Only stdlib. Loaded by path in tests (see test_installers.py).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Callable


def strip_jsonc(text: str) -> str:
    """Drop `//` line comments, `/* */` blocks and trailing commas."""
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
    """Read existing settings, tolerating JSONC. Refuses invalid JSON."""
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    for attempt in (text, strip_jsonc(text)):
        try:
            data = json.loads(attempt)
            if isinstance(data, dict):
                return data
            raise SystemExit(f"ERROR: {path} does not contain a JSON object.")
        except ValueError:
            continue
    raise SystemExit(f"ERROR: {path} is not valid JSON. Refusing to touch it.")


def entry_is_ours(entry: dict, marker: str) -> bool:
    for hook in entry.get("hooks", []) or []:
        if isinstance(hook, dict) and marker in str(hook.get("command", "")):
            return True
    # Also check string command form
    if marker in str(entry.get("command", "")):
        return True
    return False


def install_entries(
    settings: dict, command: str, marker: str, hook_events: tuple[str, ...]
) -> tuple[dict, int]:
    """Merge one `{type, command}` entry per event. Returns (settings, added)."""
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit("ERROR: existing 'hooks' value is not an object.")
    added = 0
    for event in hook_events:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            print(f"  ! skipping {event}: not a list", file=sys.stderr)
            continue
        if any(isinstance(e, dict) and marker in str(e.get("command", "")) for e in entries):
            continue  # already installed -- idempotent
        entries.append({"type": "command", "command": command})
        added += 1
    return settings, added


def uninstall_entries(settings: dict, marker: str) -> tuple[dict, int]:
    """Remove only our entries, leaving anything else intact."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings, 0
    removed = 0
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not (isinstance(e, dict) and marker in str(e.get("command", "")))]
        removed += len(entries) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    return settings, removed


def write_settings(path: Path, settings: dict) -> None:
    """Back up, then write atomically (temp file + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        print(f"  backed up -> {backup}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def run_cli(
    argv: list[str] | None,
    *,
    description: str,
    project_help: str,
    settings_path: Callable[[bool], Path],
    handler_path: Path,
    install_fn: Callable[[dict, str], tuple[dict, int]],
    uninstall_fn: Callable[[dict], tuple[dict, int]],
    queue_log: str,
    restart_note: str,
) -> int:
    """Full installer CLI flow shared by the thin wrappers.

    Only strings/paths and the (differently-shaped) install/uninstall
    functions vary per agent; backup, idempotency messaging, dry-run,
    confirmation and atomic write live here.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--project", action="store_true", help=project_help)
    parser.add_argument("--dry-run", action="store_true", help="print result, write nothing")
    parser.add_argument("--uninstall", action="store_true", help="remove our entries")
    parser.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    args = parser.parse_args(argv)

    if not args.uninstall and not handler_path.is_file():
        print(f"ERROR: handler not found at {handler_path}", file=sys.stderr)
        return 1
    command = f'"{sys.executable}" "{handler_path}"'
    path = settings_path(args.project)
    print(f"Settings file: {path}")
    settings = load_settings(path)
    if args.uninstall:
        settings, changed = uninstall_fn(settings)
        verb = "remove"
    else:
        settings, changed = install_fn(settings, command)
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
    print(f"Done. {restart_note}")
    if not args.uninstall:
        print(f"Queue: {queue_log}")
    return 0
