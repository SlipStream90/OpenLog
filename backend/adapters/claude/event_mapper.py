"""Claude Code raw payload -> Universal Event mapping.

This module and `transcript_reader.py` are where every [UNVERIFIED] assumption
about Claude Code's on-disk shapes is concentrated (ARCHITECTURE.md section 7).
If the real schema differs from what is assumed here, this file is the only one
that needs to change.

## Verification status (Article IV)

The field names and tool vocabulary below are **[UNVERIFIED]**: recalled, not
fetched. Every external-verification route was blocked in this session --
`context7`, `WebSearch`/`WebFetch`, and reads of a live `~/.claude/` install were
all denied by the permission gate. The zero-network fallback that ARCHITECTURE.md
section 10 recommends (introspect a real install) was therefore unavailable.

The mitigation is ADR-009, implemented by `probe()`: every field is looked up
under several plausible names (snake_case and camelCase), and a field found under
none of them becomes `None` with a debug log rather than a `KeyError`. A wrong
guess degrades one field to null; it does not crash the adapter or the app.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.shared.events import EventSource, EventType, UniversalEvent
from backend.shared.mapping import (
    coerce_int as _coerce_int,
    detect_framework,
    estimate_line_delta as _estimate_line_delta,
    make_probe,
    parse_usage as _parse_usage,
    relative_file as _relative_file,
)
from backend.shared.sanitize import sanitize_command
from backend.shared.timeutil import parse_timestamp, utcnow

logger = logging.getLogger(__name__)

AGENT_NAME = "claude"

# --------------------------------------------------------------------------
# Defensive field access (ADR-009)
# --------------------------------------------------------------------------

#: Candidate names per logical field, most-likely first. [UNVERIFIED]
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "session_id": ("session_id", "sessionId", "session", "sessionID"),
    "hook_event_name": ("hook_event_name", "hookEventName", "hook_event", "event"),
    "tool_name": ("tool_name", "toolName", "tool"),
    "tool_input": ("tool_input", "toolInput", "input", "parameters"),
    "tool_response": ("tool_response", "toolResponse", "output", "result"),
    "timestamp": ("timestamp", "time", "created_at", "createdAt", "_received_at"),
    "prompt": ("prompt", "user_prompt", "userPrompt", "message"),
    "file_path": ("file_path", "filePath", "path", "notebook_path", "notebookPath"),
    "command": ("command", "cmd"),
    "cwd": ("cwd", "workingDirectory", "working_directory"),
    "model": ("model", "modelName", "model_name"),
    "usage": ("usage", "token_usage", "tokenUsage"),
    "exit_code": ("exit_code", "exitCode", "returncode", "status"),
}


probe = make_probe(FIELD_ALIASES)


# --------------------------------------------------------------------------
# Tool -> event vocabulary  [UNVERIFIED]
# --------------------------------------------------------------------------

#: Tools that read a file. Mapped on PreToolUse (the open is the observable act).
READ_TOOLS = frozenset({"Read", "NotebookRead"})

#: Tools that change a file. Mapped on PostToolUse -- only a completed edit is a
#: real modification; mapping PreToolUse would count edits that then failed.
WRITE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit", "Update"})

#: Shell execution.
SHELL_TOOLS = frozenset({"Bash", "BashOutput", "Shell"})

_TEST_PATTERN = re.compile(
    r"\b(pytest|jest|vitest|mocha|unittest|go\s+test|cargo\s+test|npm\s+(run\s+)?test|"
    r"yarn\s+test|pnpm\s+test|rspec|phpunit|dotnet\s+test|gradle\s+test|mvn\s+test)\b",
    re.IGNORECASE,
)
_BUILD_PATTERN = re.compile(
    r"\b(npm\s+run\s+build|yarn\s+build|pnpm\s+build|make\b|cargo\s+build|go\s+build|"
    r"docker\s+build|gradle\s+build|mvn\s+(package|install)|tsc\b|webpack\b|vite\s+build)\b",
    re.IGNORECASE,
)
_GIT_COMMIT_PATTERN = re.compile(r"\bgit\s+(-[^\s]+\s+)*commit\b", re.IGNORECASE)


def _map_session_start(payload: dict[str, Any], build, cwd) -> list[UniversalEvent]:
    return [build(EventType.SESSION_STARTED)]


def _map_session_end(payload: dict[str, Any], build, cwd) -> list[UniversalEvent]:
    return [build(EventType.SESSION_ENDED)]


def _map_prompt_submit(payload: dict[str, Any], build, cwd) -> list[UniversalEvent]:
    prompt = probe(payload, "prompt")
    length = len(prompt) if isinstance(prompt, str) else 0
    return [build(EventType.PROMPT_SUBMITTED, metadata={"length": length})]


def _map_tool_use_hook(payload: dict[str, Any], build, cwd, normalized_hook: str) -> list[UniversalEvent]:
    return _map_tool_use(payload, normalized_hook, cwd, build)


def _map_unknown_hook(payload: dict[str, Any], hook_name: str, build, cwd) -> list[UniversalEvent]:
    logger.debug("Dropping unmapped hook event %r", hook_name)
    return []


_HOOK_DISPATCH: dict[str, callable] = {
    "sessionstart": lambda p, b, c: _map_session_start(p, b, c),
    "sessionend": lambda p, b, c: _map_session_end(p, b, c),
    "stop": lambda p, b, c: _map_session_end(p, b, c),
    "userpromptsubmit": lambda p, b, c: _map_prompt_submit(p, b, c),
    "pretooluse": lambda p, b, c: _map_tool_use_hook(p, b, c, "pretooluse"),
    "posttooluse": lambda p, b, c: _map_tool_use_hook(p, b, c, "posttooluse"),
    "notification": lambda p, b, c: _map_unknown_hook(p, "notification", b, c),
}


def detect_test_framework(command: str) -> str | None:
    """Best-effort framework label for a test command. `None` when unclear.

    Explicitly a heuristic (data_models.md section 2). Returning `None` is a
    perfectly good answer -- guessing a framework would put a fabricated value
    into the record.
    """
    return detect_framework(command, _TEST_PATTERN)


# --------------------------------------------------------------------------
# Hook payload mapping
# --------------------------------------------------------------------------


def map_hook_payload(payload: dict[str, Any]) -> list[UniversalEvent]:
    """Normalize one queue-file line into zero or more Universal Events.

    Returns a list because one raw payload can legitimately be more than one
    observation: a completed `pytest` run is both a `terminal_command` (it goes
    in the Commands table) and a `test_passed`/`test_failed` (it feeds the Tests
    metric). Collapsing those into one event would lose one of the two.
    """
    if payload.get("_unparseable"):
        logger.debug("Skipping unparseable hook payload")
        return []

    hook_name = probe(payload, "hook_event_name")
    if not isinstance(hook_name, str) or not hook_name:
        logger.debug("Hook payload with no identifiable hook name; skipping")
        return []

    session_id = probe(payload, "session_id")
    session_id = str(session_id) if session_id else None

    received = payload.get("_received_at")
    timestamp = parse_timestamp(
        probe(payload, "timestamp"),
        default=parse_timestamp(received) if received else utcnow(),
    )
    cwd = probe(payload, "cwd")

    def build(
        event: EventType,
        *,
        file: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UniversalEvent:
        return UniversalEvent(
            session_id=session_id or "",
            timestamp=timestamp,
            agent=AGENT_NAME,
            event=event,
            model=None,  # hooks do not expose the model; transcripts enrich it
            file=file,
            metadata=metadata or {},
            source="hook",
        )

    normalized = hook_name.strip().lower().replace("_", "")

    handler = _HOOK_DISPATCH.get(normalized)
    if handler:
        return handler(payload, build, cwd)

    return _map_unknown_hook(payload, hook_name, build, cwd)


def _map_tool_use(
    payload: dict[str, Any],
    normalized_hook: str,
    cwd: Any,
    build,
) -> list[UniversalEvent]:
    tool_name = probe(payload, "tool_name")
    if not isinstance(tool_name, str):
        return []

    tool_input = probe(payload, "tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    is_post = normalized_hook == "posttooluse"

    if tool_name in READ_TOOLS and not is_post:
        file = _relative_file(probe(tool_input, "file_path"), cwd)
        if file is None:
            return []
        return [build(EventType.FILE_OPENED, file=file)]

    if tool_name in WRITE_TOOLS and is_post:
        file = _relative_file(probe(tool_input, "file_path"), cwd)
        if file is None:
            return []
        added, removed = _estimate_line_delta(tool_input)
        return [
            build(
                EventType.FILE_MODIFIED,
                file=file,
                metadata={"lines_added": added, "lines_removed": removed},
            )
        ]

    if tool_name in SHELL_TOOLS and is_post:
        return _map_shell_command(payload, tool_input, build)

    return []


def _map_shell_command(
    payload: dict[str, Any], tool_input: dict[str, Any], build
) -> list[UniversalEvent]:
    command = probe(tool_input, "command")
    if not isinstance(command, str) or not command.strip():
        return []
    # Redact secrets before anything is stored: PRD section 21. Framework /
    # build / git classification below only matches tool names, never secret
    # values, so it is unaffected by redaction.
    command = sanitize_command(command.strip()) or ""

    response = probe(payload, "tool_response")
    exit_code = None
    if isinstance(response, dict):
        exit_code = _coerce_int(probe(response, "exit_code"))

    events = [
        build(
            EventType.TERMINAL_COMMAND,
            metadata={"command": command, "exit_code": exit_code},
        )
    ]

    framework = detect_test_framework(command)
    if framework is not None:
        meta = {"command": command, "framework": framework}
        if exit_code is None:
            # Outcome genuinely unknown -- record that a test ran, but do not
            # invent a pass. A fabricated pass would corrupt the Tests metric.
            events.append(build(EventType.TEST_EXECUTED, metadata=meta))
        elif exit_code == 0:
            events.append(build(EventType.TEST_PASSED, metadata=meta))
        else:
            events.append(build(EventType.TEST_FAILED, metadata=meta))
        return events

    if _GIT_COMMIT_PATTERN.search(command):
        # Subject line only -- never the diff (data_models.md section 2).
        events.append(build(EventType.GIT_COMMIT, metadata={"message": None}))
        return events

    if _BUILD_PATTERN.search(command):
        meta = {"command": command}
        events.append(build(EventType.BUILD_STARTED, metadata=meta))
        if exit_code is not None:
            events.append(build(EventType.BUILD_FINISHED, metadata=meta))
        return events

    return events


# `_estimate_line_delta` is `backend.shared.mapping.estimate_line_delta`
# (imported above): the per-agent key tables were unified there.


# --------------------------------------------------------------------------
# Transcript record mapping
# --------------------------------------------------------------------------


# `_parse_usage` is `backend.shared.mapping.parse_usage` (imported above).


def map_transcript_record(record: dict[str, Any]) -> list[UniversalEvent]:
    """Normalize one transcript JSONL line.

    Transcripts exist to supply what hooks do not expose: model name and token
    counts (MISSION_BRIEF.md line 31). Message *text* is deliberately never
    extracted -- PRD section 21 forbids copying it into our database, and no
    in-scope metric needs it.
    """
    session_id = probe(record, "session_id")
    if not session_id:
        return []

    entry_type = record.get("type") or record.get("role")
    message = record.get("message")
    if not isinstance(message, dict):
        message = {}

    model = probe(message, "model") or probe(record, "model")
    usage = probe(message, "usage") or probe(record, "usage")

    if entry_type not in ("assistant", "response"):
        return []
    if not isinstance(usage, dict) and model is None:
        return []

    token_count, input_tokens, output_tokens = _parse_usage(usage)

    timestamp = parse_timestamp(probe(record, "timestamp"))

    return [
        UniversalEvent(
            session_id=str(session_id),
            timestamp=timestamp,
            agent=AGENT_NAME,
            event=EventType.RESPONSE_RECEIVED,
            model=str(model) if model else None,
            file=None,
            metadata={
                "token_count": token_count,
                "model": str(model) if model else None,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            source="transcript",
        )
    ]


def map_payload(payload: dict[str, Any], source: EventSource) -> list[UniversalEvent]:
    """Dispatch to the right mapper for a payload's provenance."""
    if source == "transcript":
        return map_transcript_record(payload)
    return map_hook_payload(payload)
