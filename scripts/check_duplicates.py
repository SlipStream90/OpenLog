#!/usr/bin/env python3
"""Detect copy-pasted code blocks across the Python backend.

    uv run python scripts/check_duplicates.py
    uv run python scripts/check_duplicates.py --min-lines 25 --json
    uv run python scripts/check_duplicates.py --ignore "backend/adapters/*/event_mapper.py"

Scans ``backend/`` and ``scripts/`` for identical normalized line-windows
appearing in two or more files. Normalization strips comments and blank lines
and collapses whitespace, so reformatted copies still match.

Exit status: 0 when no duplicates at or above ``--min-lines`` are found,
1 when duplicates are reported, 2 on usage errors. Pass ``--ignore`` globs
for known-intentional duplication (per-adapter parsing is isolated on purpose
per PRD section 18 -- every adapter re-implements the same mapping shape
against a different on-disk schema, so some overlap is expected).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("backend", "scripts")


def normalize_lines(path: Path) -> list[str]:
    """Return significant lines: comments/blanks removed, whitespace collapsed."""
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Drop trailing inline comments (naive: fine for a heuristic tool).
        code = raw.split("#", 1)[0]
        collapsed = " ".join(code.split())
        if collapsed:
            out.append(collapsed)
    return out


def find_duplicates(
    files: list[Path], min_lines: int
) -> list[dict]:
    """Find normalized windows of >= min_lines shared by 2+ files."""
    index: dict[str, dict] = {}
    for path in files:
        try:
            lines = normalize_lines(path)
        except OSError:
            continue
        seen_in_file: set[str] = set()
        for start in range(len(lines) - min_lines + 1):
            window = lines[start : start + min_lines]
            digest = hashlib.sha256("\n".join(window).encode()).hexdigest()
            if digest in seen_in_file:
                continue  # same block repeated inside one file: not cross-file dup
            seen_in_file.add(digest)
            entry = index.setdefault(digest, {"files": [], "sample": window[:5]})
            rel = str(path.relative_to(ROOT))
            if rel not in entry["files"]:
                entry["files"].append(rel)
    groups = [
        {"hash": digest[:12], "files": sorted(e["files"]), "sample": e["sample"]}
        for digest, e in index.items()
        if len(e["files"]) >= 2
    ]
    groups.sort(key=lambda g: (-len(g["files"]), g["files"][0]))
    # Overlapping sliding windows over the same copied region produce many
    # groups with identical file sets. Merge those so one copied region reads
    # as one report, with a window count showing its size.
    merged: list[dict] = []
    for g in groups:
        key = tuple(g["files"])
        if merged and tuple(merged[-1]["files"]) == key:
            merged[-1]["windows"] += 1
        else:
            g["windows"] = 1
            merged.append(g)
    merged.sort(key=lambda g: (-len(g["files"]), -g["windows"], g["files"][0]))
    return merged


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-lines", type=int, default=25)
    parser.add_argument("--ignore", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.min_lines < 5:
        parser.error("--min-lines must be >= 5")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    files: list[Path] = []
    for dirname in SCAN_DIRS:
        base = ROOT / dirname
        if base.is_dir():
            files.extend(sorted(base.rglob("*.py")))
    ignored = [p for p in files if any(fnmatch.fnmatch(str(p.relative_to(ROOT)), g) for g in args.ignore)]
    files = [p for p in files if p not in set(ignored)]

    groups = find_duplicates(files, args.min_lines)
    if args.json:
        print(json.dumps({"min_lines": args.min_lines, "groups": groups}, indent=2))
    elif groups:
        print(f"{len(groups)} duplicate block(s) >= {args.min_lines} lines:")
        for g in groups:
            extra = f" ({g['windows']} windows)" if g.get("windows", 1) > 1 else ""
            print(f"\n  [{g['hash']}] in {len(g['files'])} files{extra}:")
            for f in g["files"]:
                print(f"    - {f}")
            print("    e.g.:")
            for line in g["sample"]:
                print(f"      {line[:100]}")
    else:
        print(f"No duplicate blocks >= {args.min_lines} lines in {len(files)} files.")
    return 1 if groups else 0


if __name__ == "__main__":
    raise SystemExit(main())
