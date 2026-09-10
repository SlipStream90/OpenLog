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
[UNVERIFIED] — see header in `install_claude_hooks.py` for the same caveat.

    python scripts/install_kilocode_hooks.py            # install to VS Code User settings
    python scripts/install_kilocode_hooks.py --project  # install to ./.vscode/settings.json
    python scripts/install_kilocode_hooks.py --dry-run
    python scripts/install_kilocode_hooks.py --uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

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


def _strip_jsonc(text: str) -> str:
    # Remove // comments and /* */ and trailing commas for VS Code JSONC
    import re

    # strip // comments (but not inside strings — approximate)
    lines = []
    for line in text.splitlines():
        # naive: remove // after // not in quotes
        if "//" in line:
            # count quotes before //
            idx = line.find("//")
            before = line[:idx]
            if before.count('"') % 2 == 0:
                line = before
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    # trailing commas before } or ]
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
    raise SystemExit(f"ERROR: {path} is not valid JSON. Try fixing trailing commas/comments.")


def install(settings: dict, command: str) -> tuple[dict, int]:
    # Primary: kilocode.hooks array
    hooks = settings.setdefault("kilocode.hooks", [])
    # VS Code settings keys may be dotted; ensure we handle dict-style too
    # If user already has "kilocode" object, prefer it
    kilocode_obj = settings.get("kilocode")
    target_list = None
    if isinstance(kilocode_obj, dict):
        target_list = kilocode_obj.setdefault("hooks", [])
    elif "kilocode.hooks" in settings and isinstance(settings["kilocode.hooks"], list):
        target_list = settings["kilocode.hooks"]
    else:
        # Fallback generic key
        target_list = settings.setdefault("aiObservatory.kilocodeHook", [])

    # Normalize to list
    if not isinstance(target_list, list):
        raise SystemExit("ERROR: existing hooks value is not a list.")
    # Actually use kilocode_obj path if present, else dotted key path
    # We'll write to both plausible locations for robustness, but count once
    added = 0
    # Check if marker already present in any plausible location
    def contains_marker(lst):
        return any(MARKER in str(e) for e in lst)

    # Write to kilocode_obj if it exists or we can create it
    candidates = []
    if isinstance(kilocode_obj, dict):
        candidates.append(kilocode_obj["hooks"])
    if "kilocode.hooks" in settings and isinstance(settings["kilocode.hooks"], list):
        candidates.append(settings["kilocode.hooks"])
    if not candidates:
        # No candidate yet — create the dotted key as primary
        candidates.append(settings.setdefault("kilocode.hooks", []))
        # Also mirror into object form for editors that prefer it
        if not isinstance(settings.get("kilocode"), dict):
            settings.setdefault("kilocode", {})["hooks"] = candidates[0]

    for lst in candidates:
        if not contains_marker(lst):
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
    parser = argparse.ArgumentParser(description="Install Kilo Code hook.")
    parser.add_argument("--project", action="store_true", help="use ./.vscode/settings.json")
    parser.add_argument("--dry-run", action="store_true", help="print result")
    parser.add_argument("--uninstall", action="store_true", help="remove entries")
    parser.add_argument("--yes", "-y", action="store_true", help="skip prompt")
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
        print(f"Nothing to {verb}.")
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
    print("Done. Reload VS Code to apply.")
    if not args.uninstall:
        print(f"Queue: {Path.home() / '.ai-observatory' / 'logs' / 'kilocode_hooks.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
