"""Adapter normalization tests -- hook/transcript payload -> UniversalEvent.

The point of these tests is not only "does it map correctly" but "does it
degrade correctly", since the input schema is [UNVERIFIED] (ADR-009). Roughly
half the cases below feed the adapter something it did not expect.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.adapters.claude import event_mapper
from backend.adapters.claude.adapter import ClaudeAdapter
from backend.shared.events import EventType, UniversalEvent


@pytest.fixture
def adapter():
    a = ClaudeAdapter()
    a.initialize()
    return a


# -- Happy path -------------------------------------------------------------


def test_edit_hook_becomes_file_modified(adapter, hook_payload):
    events = adapter.capture_events(hook_payload(), "hook")

    assert len(events) == 1
    event = events[0]
    assert event.event is EventType.FILE_MODIFIED
    assert event.session_id == "sess-abc123"
    # Path is stored relative to cwd, not as the developer's absolute path.
    assert event.file == "backend/app.py"
    assert event.metadata["lines_added"] == 2
    assert event.metadata["lines_removed"] == 0
    assert event.timestamp.tzinfo is not None


def test_read_hook_becomes_file_opened(adapter, hook_payload):
    events = adapter.capture_events(
        hook_payload(
            hook_event_name="PreToolUse",
            tool_name="Read",
            tool_input={"file_path": "/home/dev/project/auth.py"},
        ),
        "hook",
    )
    assert [e.event for e in events] == [EventType.FILE_OPENED]
    assert events[0].file == "auth.py"


def test_prompt_submitted_records_length_never_text(adapter, hook_payload):
    secret = "my prompt containing an API key sk-do-not-store-me"
    events = adapter.capture_events(
        hook_payload(hook_event_name="UserPromptSubmit", prompt=secret, tool_input={}),
        "hook",
    )

    assert len(events) == 1
    event = events[0]
    assert event.event is EventType.PROMPT_SUBMITTED
    assert event.metadata == {"length": len(secret)}
    # The privacy constraint is the whole reason this event type exists in this
    # shape -- assert the text is nowhere in the serialized event.
    assert secret not in json.dumps(event.metadata)


def test_session_start_and_end(adapter, hook_payload):
    started = adapter.capture_events(
        hook_payload(hook_event_name="SessionStart", tool_input={}), "hook"
    )
    ended = adapter.capture_events(
        hook_payload(hook_event_name="SessionEnd", tool_input={}), "hook"
    )
    assert [e.event for e in started] == [EventType.SESSION_STARTED]
    assert [e.event for e in ended] == [EventType.SESSION_ENDED]


# -- Multi-event fan-out ----------------------------------------------------


def test_passing_test_command_yields_command_and_test_passed(adapter, hook_payload):
    events = adapter.capture_events(
        hook_payload(
            tool_name="Bash",
            tool_input={"command": "uv run pytest -q"},
            tool_response={"exit_code": 0},
        ),
        "hook",
    )

    kinds = [e.event for e in events]
    assert EventType.TERMINAL_COMMAND in kinds
    assert EventType.TEST_PASSED in kinds
    assert events[0].metadata["command"] == "uv run pytest -q"


def test_failing_test_command_yields_test_failed(adapter, hook_payload):
    events = adapter.capture_events(
        hook_payload(
            tool_name="Bash",
            tool_input={"command": "pytest"},
            tool_response={"exit_code": 1},
        ),
        "hook",
    )
    assert EventType.TEST_FAILED in [e.event for e in events]


def test_test_command_without_exit_code_does_not_fabricate_a_pass(adapter, hook_payload):
    """An unknown outcome must record test_executed, never test_passed."""
    events = adapter.capture_events(
        hook_payload(tool_name="Bash", tool_input={"command": "pytest"}),
        "hook",
    )
    kinds = [e.event for e in events]
    assert EventType.TEST_EXECUTED in kinds
    assert EventType.TEST_PASSED not in kinds
    assert EventType.TEST_FAILED not in kinds


def test_git_commit_command_yields_git_commit(adapter, hook_payload):
    events = adapter.capture_events(
        hook_payload(
            tool_name="Bash",
            tool_input={"command": 'git commit -m "add auth"'},
            tool_response={"exit_code": 0},
        ),
        "hook",
    )
    assert EventType.GIT_COMMIT in [e.event for e in events]
    # The commit message is not harvested -- it can contain anything.
    commit = next(e for e in events if e.event is EventType.GIT_COMMIT)
    assert commit.metadata.get("message") is None


# -- Defensive probing (ADR-009) -------------------------------------------


def test_camelcase_field_names_are_probed(adapter):
    """The whole ADR-009 mitigation in one test: camelCase must work too."""
    events = adapter.capture_events(
        {
            "sessionId": "sess-camel",
            "hookEventName": "PreToolUse",
            "toolName": "Read",
            "toolInput": {"filePath": "src/main.py"},
        },
        "hook",
    )
    assert len(events) == 1
    assert events[0].session_id == "sess-camel"
    assert events[0].file == "src/main.py"


def test_missing_session_id_is_bucketed_not_dropped(adapter, hook_payload):
    """ADR-001: an orphan event is still evidence something happened."""
    payload = hook_payload()
    del payload["session_id"]

    events = adapter.capture_events(payload, "hook")

    assert len(events) == 1
    assert events[0].session_id.startswith("unmatched-claude-")


def test_unmapped_payloads_return_empty_not_raise(adapter):
    for payload in (
        {},
        {"hook_event_name": "SomethingNewClaudeAdded", "session_id": "s"},
        {"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "Glob"},
        {"_unparseable": True},
        {"session_id": None, "hook_event_name": None},
    ):
        assert adapter.capture_events(payload, "hook") == []


def test_malformed_input_types_never_raise(adapter):
    assert adapter.capture_events("not a dict", "hook") == []  # type: ignore[arg-type]
    assert adapter.capture_events(None, "hook") == []  # type: ignore[arg-type]
    assert adapter.capture_events({"hook_event_name": 12345}, "hook") == []


def test_capture_event_singular_honours_the_declared_contract(adapter, hook_payload):
    """data_models.md section 5 declares this signature; it must still hold."""
    result = adapter.capture_event(hook_payload(), "hook")
    assert isinstance(result, UniversalEvent)
    assert adapter.capture_event({"nothing": "here"}, "hook") is None


# -- Transcript mapping -----------------------------------------------------


def test_transcript_record_yields_response_received_with_tokens(adapter):
    events = adapter.capture_events(
        {
            "type": "assistant",
            "sessionId": "sess-abc123",
            "timestamp": "2026-01-15T10:15:23Z",
            "message": {
                "model": "claude-sonnet-4-5",
                "usage": {"input_tokens": 1200, "output_tokens": 340},
            },
        },
        "transcript",
    )

    assert len(events) == 1
    event = events[0]
    assert event.event is EventType.RESPONSE_RECEIVED
    assert event.model == "claude-sonnet-4-5"
    assert event.metadata["token_count"] == 1540
    assert event.source == "transcript"


def test_transcript_user_messages_are_ignored(adapter):
    """User message text must never become an event -- nothing needs it."""
    assert (
        adapter.capture_events(
            {"type": "user", "sessionId": "s", "message": {"content": "secret text"}},
            "transcript",
        )
        == []
    )


def test_unpriced_model_costs_zero_rather_than_a_guess(adapter):
    event = adapter.capture_events(
        {
            "type": "assistant",
            "sessionId": "s",
            "message": {
                "model": "claude-sonnet-4-5",
                "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
            },
        },
        "transcript",
    )[0]
    # No pricing.json in the temp home => 0.0, not an invented dollar figure.
    assert adapter.estimate_cost(event) == 0.0


# -- Framework detection ----------------------------------------------------


@pytest.mark.parametrize(
    "command,expected",
    [
        ("pytest tests/", "pytest"),
        ("npm test", "npm test"),
        ("cargo test --all", "cargo test"),
        ("ls -la", None),
        ("echo 'pytest is great'", "pytest"),  # known heuristic limitation
        ("", None),
    ],
)
def test_detect_test_framework(command, expected):
    assert event_mapper.detect_test_framework(command) == expected


# -- Hook handler (subprocess) ---------------------------------------------


def _run_handler(stdin_text: str, home: Path) -> subprocess.CompletedProcess:
    handler = (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "adapters"
        / "claude"
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


def test_hook_handler_appends_one_line(temp_home):
    payload = json.dumps({"session_id": "s1", "hook_event_name": "SessionStart"})
    result = _run_handler(payload, temp_home)

    assert result.returncode == 0
    queue = temp_home / "logs" / "claude_hooks.jsonl"
    lines = queue.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["session_id"] == "s1"
    assert "_received_at" in record


def test_hook_handler_never_fails_visibly(temp_home):
    """ADR-007: garbage in must still mean exit 0 and a silent stderr."""
    for stdin_text in ("", "   ", "not json at all", "[1,2,3]"):
        result = _run_handler(stdin_text, temp_home)
        assert result.returncode == 0, f"non-zero exit for {stdin_text!r}"
        assert result.stderr == "", f"stderr written for {stdin_text!r}"


def test_hook_handler_imports_only_stdlib():
    """The hot-path constraint, enforced rather than trusted.

    Importing anything from `backend.*` here would add real latency to every
    tool call in the user's session.
    """
    source = (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "adapters"
        / "claude"
        / "hook_handler.py"
    ).read_text(encoding="utf-8")

    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "backend" not in stripped, f"non-stdlib import: {stripped}"
            assert "sqlalchemy" not in stripped.lower()
            assert "fastapi" not in stripped.lower()
