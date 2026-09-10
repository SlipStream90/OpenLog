#!/usr/bin/env python3
"""Write today's Markdown summary to the local analytics directory.

    uv run python scripts/daily_summary.py
    uv run python scripts/daily_summary.py --api-url http://localhost:3141

Reads only from the local API (never the network beyond localhost) and writes
`~/.ai-observatory/analytics/YYYY-MM-DD.md` (PRD sections 22-23: export
location + Markdown summary). Stdlib only, so it works wherever Python does.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

from backend.shared import paths


def _get(api_url: str, path: str):
    try:
        with urllib.request.urlopen(api_url.rstrip("/") + path, timeout=10) as response:
            return json.load(response)
    except Exception as exc:
        print(f"error: cannot reach {api_url}{path}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _fmt_seconds(seconds: float) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def render(stats: dict, files: dict, day: str) -> str:
    lines = [
        f"# AI Observatory -- {day}",
        "",
        f"- Coding time: {_fmt_seconds(stats.get('coding_time_seconds', 0))}",
        f"- Sessions: {stats.get('session_count', 0)}",
        f"- Files changed: {stats.get('files_changed_count', 0)}",
        f"- Commands: {stats.get('command_count', 0)}",
        f"- Tests: {stats.get('test_count', 0)}",
    ]
    cost = stats.get("estimated_cost", 0.0)
    if stats.get("cost_is_estimated"):
        lines.append(f"- Estimated cost: ${cost:.4f}")
    else:
        lines.append("- Estimated cost: no pricing configured")
    lines += ["", "## Top files", ""]
    top = (files.get("files") or [])[:10]
    if not top:
        lines.append("No file activity recorded.")
    for entry in top:
        lines.append(
            f"- `{entry['filename']}` -- {entry['total_modifications']} edits "
            f"(+{entry['total_additions']}/-{entry['total_deletions']}, "
            f"{entry['session_count']} sessions)"
        )
    lines += ["", "_Generated locally by AI Observatory; no data left this machine._", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:3141")
    parser.add_argument("--day", default=date.today().isoformat())
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    stats = _get(args.api_url, "/stats")
    files = _get(args.api_url, "/files")
    out = Path(args.out) if args.out else paths.analytics_dir() / f"{args.day}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(stats, files, args.day), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
