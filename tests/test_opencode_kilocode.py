"""OpenCode + Kilo Code adapter tests -- mirrors test_adapter.py's contract.

Both adapters implement the same `Adapter` protocol as Claude's (initialize,
start/end_session, capture_event(s), estimate_cost) and the same degradation
guarantees (ADR-001 bucketing, ADR-007 silent hooks, ADR-009 probing, prompt
lengths never text, secrets redacted from commands). These tests pin that.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.adapters.kilocode.adapter import KiloCodeAdapter
from backend.adapters.opencode.adapter import OpenCodeAdapter
from backend.shared.events import EventType


@pytest.fixture(params=["opencode", "kilocode"])
def any_adapter(request):
    cls = OpenCodeAdapter if request.param == "opencode" else KiloCodeAdapter
    adapter = cls()
    adapter.initialize()
    return adapter


def _shell_payload(tool_name, command, exit_code=None, session_id="sess-x"):
    payload = {
        "session_id": session_id,
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": {"command": command},
    }
    if exit_code is not None:
        payload["tool_response"] = {"exit_code": exit_code}
    return payload


# -- Shared contract --------------------------------------------------------


def test_session_lifecycle(any_adapter):
    assert any_adapter.name in ("opencode", "kilocode")
    any_adapter.start_session("s", {})
    any_adapter.end_session("s", {})
    assert any_adapter.estimate_cost(None) == 0.0  # type: ignore[arg-type]


def test_passing_test_command_fans_out(any_adapter):
    tool = "bash" if any_adapter.name == "opencode" else "execute_command"
    events = any_adapter.capture_events(
        _shell_payload(tool, "uv run pytest -q", exit_code=0), "hook"
    )
    kinds = [e.event for e in events]
    assert EventType.TERMINAL_COMMAND in kinds
    assert EventType.TEST_PASSED in kinds
    assert events[0].agent == any_adapter.name


def test_failing_test_command_yields_test_failed(any_adapter):
    tool = "bash" if any_adapter.name == "opencode" else "execute_command"
    events = any_adapter.capture_events(
        _shell_payload(tool, "pytest", exit_code=1), "hook"
    )
    assert EventType.TEST_FAILED in [e.event for e in events]


def test_missing_session_id_is_bucketed_not_dropped(any_adapter):
    payload = _shell_payload("bash", "ls")
    del payload["session_id"]
    events = any_adapter.capture_events(payload, "hook")
    assert events, "expected fallback tool mapping to produce an event"
    assert events[0].session_id.startswith(f"unmatched-{any_adapter.name}-")


def test_malformed_input_never_raises(any_adapter):
    assert any_adapter.capture_events("not a dict", "hook") == []  # type: ignore[arg-type]
    assert any_adapter.capture_events(None, "hook") == []  # type: ignore[arg-type]
    assert any_adapter.capture_events({}, "hook") == []
    assert any_adapter.capture_events({"_unparseable": True}, "hook") == []


def test_secrets_redacted_end_to_end(any_adapter):
    """A secret in argv must not survive normalization (PRD section 21)."""
    tool = "bash" if any_adapter.name == "opencode" else "execute_command"
    events = any_adapter.capture_events(
        _shell_payload(tool, "export OPENAI_API_KEY=sk-topsecret12345678 && npm test"),
        "hook",
    )
    assert events
    blob = json.dumps([e.metadata for e in events])
    assert "sk-topsecret12345678" not in blob
    assert "[REDACTED]" in blob


# -- OpenCode specifics -----------------------------------------------------


@pytest.fixture
def opencode():
    adapter = OpenCodeAdapter()
    adapter.initialize()
    return adapter


def test_opencode_nested_message_prompt_length(opencode):
    events = opencode.capture_events(
        {
            "session_id": "s",
            "hook_event_name": "userpromptsubmit",
            "message": {"content": "hello there"},
        },
        "hook",
    )
    assert len(events) == 1
    assert events[0].event is EventType.PROMPT_SUBMITTED
    assert events[0].metadata == {"length": len("hello there")}


def test_opencode_tool_fallback_without_hook_name(opencode):
    """Unknown hook names carrying a tool still map (PostToolUse inferred)."""
    events = opencode.capture_events(
        {
            "session_id": "s",
            "action": "something-brand-new",
            "tool_name": "bash",
            "tool_input": {"command": "ls"},
            "tool_response": {"exit_code": 0},
        },
        "hook",
    )
    assert EventType.TERMINAL_COMMAND in [e.event for e in events]


def test_opencode_transcript_usage(opencode):
    events = opencode.capture_events(
        {
            "type": "assistant",
            "session_id": "sess-o",
            "message": {
                "model": "gpt-4o",
                "usage": {"inputTokens": 100, "outputTokens": 50},
            },
        },
        "transcript",
    )
    assert len(events) == 1
    assert events[0].event is EventType.RESPONSE_RECEIVED
    assert events[0].metadata["token_count"] == 150


# -- Kilo Code specifics ----------------------------------------------------


@pytest.fixture
def kilocode():
    adapter = KiloCodeAdapter()
    adapter.initialize()
    return adapter


def test_kilocode_read_and_write(kilocode):
    opened = kilocode.capture_events(
        {
            "session_id": "s",
            "hook_event_name": "PreToolUse",
            "tool_name": "read_file",
            "tool_input": {"path": "/proj/a.py"},
            "cwd": "/proj",
        },
        "hook",
    )
    assert [e.event for e in opened] == [EventType.FILE_OPENED]
    assert opened[0].file == "a.py"

    modified = kilocode.capture_events(
        {
            "session_id": "s",
            "hook_event_name": "PostToolUse",
            "tool_name": "replace_in_file",
            "tool_input": {"path": "/proj/a.py", "diff": "@@ -1,2 +1,3 @@\n+new\n"},
            "cwd": "/proj",
        },
        "hook",
    )
    assert [e.event for e in modified] == [EventType.FILE_MODIFIED]
    assert modified[0].metadata["lines_added"] == 1


def test_kilocode_task_id_session_fallback(kilocode):
    events = kilocode.capture_events(
        {
            "type": "ai",
            "taskId": "task-7",
            "message": {"model": "claude-sonnet", "usage": {"input_tokens": 5}},
        },
        "transcript",
    )
    assert len(events) == 1
    assert events[0].session_id == "task-7"


# -- Hook handlers (subprocess) ---------------------------------------------


def _run_handler(agent: str, stdin_text: str, home: Path) -> subprocess.CompletedProcess:
    handler = (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "adapters"
        / agent
        / "hook_handler.py"
    )
    return subprocess.run(
        [sys.executable, str(handler)],
        input=stdin_text,
        capture_output=True,
        text=True,
        env={**os.environ, "AI_OBSERVATORY_HOME": str(home)},
        timeout=30,
    )


@pytest.mark.parametrize(
    "agent,queue_file",
    [("opencode", "opencode_hooks.jsonl"), ("kilocode", "kilocode_hooks.jsonl")],
)
def test_hook_handler_appends_and_never_fails(temp_home, agent, queue_file):
    result = _run_handler(
        agent, json.dumps({"session_id": "s1", "hook_event_name": "x"}), temp_home
    )
    assert result.returncode == 0
    lines = (temp_home / "logs" / queue_file).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["session_id"] == "s1"

    for bad in ("", "not json", "[1,2]"):
        result = _run_handler(agent, bad, temp_home)
        assert result.returncode == 0
        assert result.stderr == ""


@pytest.mark.parametrize("agent", ["opencode", "kilocode"])
def test_hook_handler_imports_only_stdlib(agent):
    source = (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "adapters"
        / agent
        / "hook_handler.py"
    ).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "backend" not in stripped, f"non-stdlib import: {stripped}"
