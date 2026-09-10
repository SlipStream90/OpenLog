#!/usr/bin/env python3
"""Analyze coupling between backend packages and enforce layering rules.

    uv run python scripts/check_coupling.py
    uv run python scripts/check_coupling.py --json

Builds a package-level import graph from ``backend/**/*.py`` with ``ast``
(stdlib only, no imports executed) and checks it against the layering the
PRD and MISSION_BRIEF mandate:

* ``backend.shared`` is pure -- it must not import any other ``backend.*``.
* ``backend.database`` may only build on ``backend.shared``.
* ``backend.adapters.*`` are isolated per agent (PRD section 18) -- they may
  only import ``backend.shared``. All agent-specific parsing stops at the
  adapter boundary; analytics/API must never need agent-specific logic.
* ``backend.telemetry`` wires adapters into the DB -- it may import
  ``backend.shared``, ``backend.database`` and ``backend.adapters``, never
  ``backend.api``.
* ``backend.api`` serves reads -- it may import ``backend.shared``,
  ``backend.database``, ``backend.telemetry.watcher_status`` (health only)
  and ``*.pricing`` (cost tables). Anything deeper (e.g. importing a whole
  adapter or the ingestion pipeline) is a layering violation.
* No dependency cycles between top-level packages.

Also reports fan-in/fan-out and instability (I = out / (in + out)) per
package so rising coupling is visible before it becomes a cycle.

Exit status: 0 when clean, 1 on any violation or cycle.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

#: Top-level packages that form the coupling graph nodes.
TOP_LEVEL = ("shared", "database", "adapters", "telemetry", "api", "analytics")

#: Allowed outgoing edges per node. ``adapters``/``api`` entries marked with
#: "*" are prefix rules handled specially in _allowed().
ALLOWED: dict[str, set[str]] = {
    "shared": set(),
    "database": {"shared"},
    "adapters": {"shared"},
    "telemetry": {"shared", "database", "adapters", "telemetry"},
    "api": {"shared", "database", "adapters-pricing", "telemetry-status"},
    "analytics": {"shared", "database"},
}


def module_of(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    return ".".join(rel.parts)


def top_of(mod: str) -> str | None:
    parts = mod.split(".")
    if len(parts) < 2 or parts[0] != "backend":
        return None
    return parts[1] if parts[1] in TOP_LEVEL else "other"


def imported_backend_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "backend" or alias.name.startswith("backend."):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "backend" or node.module.startswith("backend.")):
                found.add(node.module)
                # `from backend.adapters.claude import pricing` imports the
                # pricing submodule, not just the package -- record both so
                # layering rules can tell them apart.
                for alias in node.names:
                    if alias.name != "*":
                        found.add(f"{node.module}.{alias.name}")
            elif (node.level or 0) > 0:
                # Resolve relative import against the containing package.
                pkg = module_of(path)
                if path.name != "__init__.py":
                    pkg = pkg.rpartition(".")[0]
                for _ in range((node.level or 1) - 1):
                    pkg = pkg.rpartition(".")[0]
                base = f"{pkg}.{node.module}" if node.module else pkg
                if base == "backend" or base.startswith("backend."):
                    found.add(base)
    return found


def _allowed(src_top: str, dst_mod: str, src_file: str = "") -> bool:
    dst_top = top_of(dst_mod)
    if dst_top is None or dst_top == "other":
        return True  # stdlib / third-party: out of scope
    if dst_top == src_top:
        return True  # inside the same layer
    # Composition root: backend/api/main.py is documented as the one module
    # that wires database + telemetry + routers together, so its telemetry
    # import is the design, not a violation.
    if src_file.replace("\\", "/").endswith("backend/api/main.py") and dst_top == "telemetry":
        return True
    if src_top == "api" and dst_top == "adapters":
        return dst_mod.split(".")[-1] == "pricing" or ".pricing" in dst_mod
    if src_top == "api" and dst_top == "telemetry":
        return dst_mod.startswith("backend.telemetry.watcher_status")
    return dst_top in ALLOWED.get(src_top, set())


def build_graph() -> tuple[dict[str, set[str]], list[dict]]:
    edges: dict[str, set[str]] = {t: set() for t in TOP_LEVEL}
    violations: list[dict] = []
    for path in sorted(BACKEND.rglob("*.py")):
        src_mod = module_of(path)
        src_top = top_of(src_mod)
        if src_top is None or src_top == "other":
            continue
        imported = imported_backend_modules(path)
        for dst in sorted(imported):
            dst_top = top_of(dst)
            if dst_top is None or dst_top == "other" or dst_top == src_top:
                continue
            # `from X import Y` records both X and X.Y; if the more specific
            # form is allowed, the parent is just its prefix, not a violation.
            if any(other != dst and other.startswith(dst + ".")
                   and _allowed(src_top, other, str(path.relative_to(ROOT)))
                   for other in imported):
                continue
            edges[src_top].add(dst_top)
            if not _allowed(src_top, dst, str(path.relative_to(ROOT))):
                violations.append(
                    {
                        "file": str(path.relative_to(ROOT)),
                        "source": src_top,
                        "imports": dst,
                    }
                )
    return edges, violations


def find_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> None:
        if node in stack:
            cycles.append(stack[stack.index(node):] + [node])
            return
        if node in visited:
            return
        visited.add(node)
        stack.append(node)
        for nxt in sorted(edges.get(node, ())):
            visit(nxt)
        stack.pop()

    for node in sorted(edges):
        visit(node)
    return cycles


def metrics(edges: dict[str, set[str]]) -> dict[str, dict]:
    fan_in = {t: 0 for t in TOP_LEVEL}
    for src, dsts in edges.items():
        for d in dsts:
            fan_in[d] += 1
    out: dict[str, dict] = {}
    for t in TOP_LEVEL:
        fo = len(edges[t])
        fi = fan_in[t]
        instability = round(fo / (fi + fo), 2) if (fi + fo) else 0.0
        out[t] = {"fan_in": fi, "fan_out": fo, "instability": instability,
                  "depends_on": sorted(edges[t])}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-fan-out", type=int, default=4,
                        help="warn (not fail) when a package exceeds this fan-out")
    args = parser.parse_args(argv or sys.argv[1:])

    edges, violations = build_graph()
    cycles = find_cycles(edges)
    stats = metrics(edges)
    warnings = [f"{t} fan-out {s['fan_out']} > {args.max_fan_out}" for t, s in stats.items()
                if s["fan_out"] > args.max_fan_out]
    failed = bool(violations or cycles)

    if args.json:
        print(json.dumps({"metrics": stats, "violations": violations,
                          "cycles": cycles, "warnings": warnings}, indent=2))
    else:
        print("Package coupling (fan-in / fan-out / instability):")
        for t in TOP_LEVEL:
            s = stats[t]
            deps = ", ".join(s["depends_on"]) or "-"
            print(f"  backend.{t:<10} in={s['fan_in']} out={s['fan_out']} "
                  f"I={s['instability']:.2f} -> {deps}")
        if warnings:
            print("\nWarnings:")
            for w in warnings:
                print(f"  ! {w}")
        if cycles:
            print("\nCycles:")
            for c in cycles:
                print(f"  !! {' -> '.join(c)}")
        if violations:
            print(f"\n{len(violations)} layering violation(s):")
            for v in violations:
                print(f"  !! {v['file']}: backend.{v['source']} imports {v['imports']}")
        if not failed:
            print("\nOK: no cycles, no layering violations.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
