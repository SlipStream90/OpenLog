"""Hook hot-path hygiene: shims stay thin and everything stays stdlib-only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ADAPTERS = _REPO_ROOT / "backend" / "adapters"
_SHIMS = {
    "claude": ("logs", "claude_hooks.jsonl"),
    "opencode": ("logs", "opencode_hooks.jsonl"),
    "kilocode": ("logs", "kilocode_hooks.jsonl"),
    "codex": ("logs", "codex_hooks.jsonl"),
}


def _stdlib_only(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "backend" not in stripped, f"non-stdlib import: {stripped}"
            for banned in ("sqlalchemy", "fastapi", "pydantic", "uvicorn"):
                assert banned not in stripped.lower()


def test_hook_common_is_stdlib_only():
    _stdlib_only(_ADAPTERS / "_hook_common.py")


@pytest.mark.parametrize("agent", sorted(_SHIMS))
def test_shims_are_thin_delegating_stubs(agent):
    path = _ADAPTERS / agent / "hook_handler.py"
    source = path.read_text(encoding="utf-8")
    _stdlib_only(path)
    assert "from _hook_common import run" in source
    # Small enough that no 25-line duplicate window can form.
    assert len(source.splitlines()) < 25


@pytest.mark.parametrize("agent", sorted(_SHIMS))
def test_shims_write_to_their_own_queue(agent, temp_home):
    handler = _ADAPTERS / agent / "hook_handler.py"
    result = subprocess.run(
        [sys.executable, str(handler)],
        input=json.dumps({"session_id": "s"}),
        capture_output=True,
        text=True,
        env={**os.environ, "AI_OBSERVATORY_HOME": str(temp_home)},
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    queue_rel = _SHIMS[agent]
    lines = (temp_home.joinpath(*queue_rel)).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["session_id"] == "s"
