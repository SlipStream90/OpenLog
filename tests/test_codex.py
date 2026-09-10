"""Codex CLI adapter tests -- same contract as the other three agents."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.adapters import registry
from backend.adapters.codex.adapter import CodexAdapter
from backend.shared.events import EventType

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def codex():
    adapter = CodexAdapter()
    adapter.initialize()
    return adapter


def test_registry_builds_all_four_agents():
    adapters = registry.build_default_adapters()
    assert set(adapters) == {"claude", "opencode", "kilocode", "codex"}
    for name, adapter in adapters.items():
        assert adapter.name == name
        # Every spec's queue/reader/transcript hooks resolve.
        assert registry.hook_queue_path_for(name).name.endswith("_hooks.jsonl")
        assert registry.reader_for(name) is not None


def test_session_lifecycle(codex):
    assert codex.name == "codex"
    codex.start_session("s", {})
    codex.end_session("s", {})
    assert codex.estimate_cost(None) == 0.0  # type: ignore[arg-type]


def test_read_and_write(codex):
    opened = codex.capture_events(
        {
            "session_id": "s",
            "hook_event_name": "PreToolUse",
            "tool_name": "read",
            "tool_input": {"path": "/proj/a.py"},
            "cwd": "/proj",
        },
        "hook",
    )
    assert [e.event for e in opened] == [EventType.FILE_OPENED]
    assert opened[0].file == "a.py"

    modified = codex.capture_events(
        {
            "session_id": "s",
            "hook_event_name": "PostToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "path": "/proj/a.py",
                "old_string": "a\n",
                "new_string": "a\nb\n",
            },
            "cwd": "/proj",
        },
        "hook",
    )
    assert [e.event for e in modified] == [EventType.FILE_MODIFIED]
    assert modified[0].metadata["lines_added"] == 1


def test_shell_command_fans_out(codex):
    events = codex.capture_events(
        {
            "thread_id": "t-1",
            "event": "PostToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "pytest"},
            "tool_response": {"exit_code": 0},
        },
        "hook",
    )
    kinds = [e.event for e in events]
    assert EventType.TERMINAL_COMMAND in kinds
    assert EventType.TEST_PASSED in kinds
    assert events[0].session_id == "t-1"


def test_missing_session_id_bucketed(codex):
    events = codex.capture_events(
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "ls"},
            "tool_response": {"exit_code": 0},
        },
        "hook",
    )
    assert events
    assert events[0].session_id.startswith("unmatched-codex-")


def test_malformed_input_never_raises(codex):
    assert codex.capture_events("nope", "hook") == []  # type: ignore[arg-type]
    assert codex.capture_events({}, "hook") == []
    assert codex.capture_events({"_unparseable": True}, "hook") == []


def test_secrets_redacted(codex):
    events = codex.capture_events(
        {
            "session_id": "s",
            "hook_event_name": "PostToolUse",
            "tool_name": "exec",
            "tool_input": {"command": "deploy --token abcDEF123"},
        },
        "hook",
    )
    assert events
    assert "abcDEF123" not in json.dumps([e.metadata for e in events])


def test_transcript_usage(codex):
    events = codex.capture_events(
        {
            "type": "assistant",
            "thread_id": "t-9",
            "message": {
                "model": "gpt-5",
                "usage": {"input_tokens": 40, "output_tokens": 20},
            },
        },
        "transcript",
    )
    assert len(events) == 1
    assert events[0].event is EventType.RESPONSE_RECEIVED
    assert events[0].metadata["token_count"] == 60


def _run_handler(stdin_text: str, home: Path) -> subprocess.CompletedProcess:
    handler = _REPO_ROOT / "backend" / "adapters" / "codex" / "hook_handler.py"
    return subprocess.run(
        [sys.executable, str(handler)],
        input=stdin_text,
        capture_output=True,
        text=True,
        env={**os.environ, "AI_OBSERVATORY_HOME": str(home)},
        timeout=30,
    )


def test_hook_handler_appends_and_never_fails(temp_home):
    result = _run_handler(json.dumps({"thread_id": "t"}), temp_home)
    assert result.returncode == 0
    lines = (temp_home / "logs" / "codex_hooks.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    for bad in ("", "not json"):
        result = _run_handler(bad, temp_home)
        assert result.returncode == 0
        assert result.stderr == ""


def test_hook_handler_imports_only_stdlib():
    source = (
        _REPO_ROOT / "backend" / "adapters" / "codex" / "hook_handler.py"
    ).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "backend" not in stripped


def _load_installer():
    spec = importlib.util.spec_from_file_location(
        "_codex_installer", _REPO_ROOT / "scripts" / "install_codex_hooks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_add_remove_idempotent():
    installer = _load_installer()
    # Idempotency keys off MARKER, as the real hook_command() carries it.
    command = f'"/usr/bin/python3" "/repo/{installer.MARKER}"'
    settings, added = installer.install({}, command)
    assert added == len(installer.HOOK_EVENTS)
    settings2, added2 = installer.install(settings, command)
    assert added2 == 0
    assert settings2 == settings
    settings3, removed = installer.uninstall(settings2)
    assert removed == added
    assert settings3.get("hooks") in (None, {})
