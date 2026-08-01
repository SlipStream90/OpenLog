#!/usr/bin/env python3
"""Register AI Observatory's hooks in Claude Code's settings.

    python scripts/install_claude_hooks.py            # install to ~/.claude/settings.json
    python scripts/install_claude_hooks.py --project  # install to ./.claude/settings.json
    python scripts/install_claude_hooks.py --dry-run  # show the diff, write nothing
    python scripts/install_claude_hooks.py --uninstall

## Safety model (ADR-008)

This script edits the user's real Claude Code configuration -- the single
highest blast-radius thing this product touches. So:

* It **backs up** the existing file to `settings.json.bak` before any write.
* It is **read-modify-write**: existing hooks and unrelated settings are
  preserved. It never regenerates the file from a template.
* It is **idempotent**: entries are matched by the `hook_handler.py` path in the
  command string, so re-running adds nothing and does not duplicate.
* It **asks for confirmation** before writing, unless `--yes` is passed.
* It writes via a temp file + atomic replace, so an interrupted run cannot leave
  the user with a truncated settings file.

## [UNVERIFIED] schema

The `hooks` structure written below is **recalled, not verified**: every
verification route (`context7`, web search/fetch, and reading a live
`~/.claude/` install) was denied by this session's permission gate. Confirm the
shape against the current Claude Code hooks documentation before relying on it.
If it is wrong, the backup file plus `--uninstall` are the recovery path, and
only this script and `event_mapper.py` need to change.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

#: Hooks we register. The mapping from these to Universal Events lives in
#: backend/adapters/claude/event_mapper.py.
HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SessionEnd",
)

#: Hooks that take a tool `matcher`. "*" means every tool; the adapter decides
#: what is interesting, so filtering here would only hide data from it.
MATCHER_EVENTS = frozenset({"PreToolUse", "PostToolUse"})

MARKER = "hook_handler.py"


def handler_path() -> Path:
    """Absolute path to the hook handler, resolved from this script's location."""
    return (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "adapters"
        / "claude"
        / "hook_handler.py"
    )


def hook_command() -> str:
    """The shell command Claude Code will run for each hook event.

    Uses the *current* interpreter's absolute path rather than bare `python`:
    the hook runs in Claude Code's environment, which may have a different PATH
    or no `python` at all.
    """
    return f'"{sys.executable}" "{handler_path()}"'


def settings_path(project: bool) -> Path:
    if project:
        return Path.cwd() / ".claude" / "settings.json"
    return Path.home() / ".claude" / "settings.json"


def load_settings(path: Path) -> dict:
    """Read existing settings. Refuses to proceed on unparseable JSON."""
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SystemExit(
            f"ERROR: {path} is not valid JSON ({exc}).\n"
            "Refusing to touch it -- fix or move the file and re-run. "
            "Overwriting it would destroy your Claude Code configuration."
        )
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR: {path} does not contain a JSON object. Refusing to modify it.")
    return data


def _entry_is_ours(entry: dict) -> bool:
    for hook in entry.get("hooks", []) or []:
        if isinstance(hook, dict) and MARKER in str(hook.get("command", "")):
            return True
    return False


def install(settings: dict, command: str) -> tuple[dict, int]:
    """Merge our hook entries in. Returns (settings, number_added)."""
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit(
            "ERROR: the existing 'hooks' value is not an object. Refusing to overwrite it."
        )

    added = 0
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            print(f"  ! skipping {event}: existing value is not a list", file=sys.stderr)
            continue

        if any(isinstance(e, dict) and _entry_is_ours(e) for e in entries):
            continue  # already installed -- idempotent

        entry: dict = {"hooks": [{"type": "command", "command": command}]}
        if event in MATCHER_EVENTS:
            entry = {"matcher": "*", **entry}
        entries.append(entry)
        added += 1

    return settings, added


def uninstall(settings: dict) -> tuple[dict, int]:
    """Remove only our entries, leaving any other hooks intact."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings, 0

    removed = 0
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not (isinstance(e, dict) and _entry_is_ours(e))]
        removed += len(entries) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            # Leave no empty husks behind.
            del hooks[event]

    if not hooks:
        settings.pop("hooks", None)
    return settings, removed


def write_settings(path: Path, settings: dict) -> None:
    """Back up, then write atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        print(f"  backed up existing settings -> {backup}")

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install AI Observatory's Claude Code hooks.")
    parser.add_argument("--project", action="store_true", help="use ./.claude/settings.json")
    parser.add_argument("--dry-run", action="store_true", help="print the result, write nothing")
    parser.add_argument("--uninstall", action="store_true", help="remove our hook entries")
    parser.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args(argv)

    handler = handler_path()
    if not args.uninstall and not handler.is_file():
        print(f"ERROR: hook handler not found at {handler}", file=sys.stderr)
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
        print(f"Nothing to {verb} -- already in the desired state.")
        return 0

    print(f"Will {verb} {changed} hook entr{'y' if changed == 1 else 'ies'}.")

    if args.dry_run:
        print("\n--- dry run, resulting settings ---")
        print(json.dumps(settings, indent=2))
        return 0

    if not args.yes:
        answer = input(f"Write changes to {path}? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted. Nothing was written.")
            return 1

    write_settings(path, settings)
    print(f"Done. Restart Claude Code for the change to take effect.")
    if not args.uninstall:
        print("\nVerify with a scratch session, then check that this file grows:")
        print(f"  {Path.home() / '.ai-observatory' / 'logs' / 'claude_hooks.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
