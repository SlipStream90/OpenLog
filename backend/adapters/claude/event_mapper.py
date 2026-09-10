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
    ToolVocabulary,
    detect_framework,
    dispatch_hook_payload,
    hook_context,
    make_probe,
    make_build,
    map_tool_use_event,
    transcript_response,
)

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

TOOL_VOCAB = ToolVocabulary(read=READ_TOOLS, write=WRITE_TOOLS, shell=SHELL_TOOLS)

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
    return map_tool_use_event(
        payload,
        normalized_hook,
        cwd,
        build,
        vocab=TOOL_VOCAB,
        probe=probe,
        test_pattern=_TEST_PATTERN,
        build_pattern=_BUILD_PATTERN,
        git_pattern=_GIT_COMMIT_PATTERN,
    )


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

    ctx = hook_context(payload, probe, AGENT_NAME)
    if ctx is None:
        return []

    hook_name = probe(payload, "hook_event_name")
    if not isinstance(hook_name, str) or not hook_name:
        logger.debug("Hook payload with no identifiable hook name; skipping")
        return []

    # Hooks do not expose the model; transcripts enrich it.
    build = make_build(ctx, AGENT_NAME)

    return dispatch_hook_payload(
        payload,
        hook_name,
        build,
        ctx.cwd,
        vocab=TOOL_VOCAB,
        probe=probe,
        test_pattern=_TEST_PATTERN,
        build_pattern=_BUILD_PATTERN,
        git_pattern=_GIT_COMMIT_PATTERN,
        resolve_hook=lambda name: name if name in _HOOK_DISPATCH else None,
        dispatch=_HOOK_DISPATCH,
        unknown_hook=_map_unknown_hook,
    )


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

    return transcript_response(
        session_id=session_id,
        record_timestamp=probe(record, "timestamp"),
        agent_name=AGENT_NAME,
        model=model,
        usage=usage,
    )


def map_payload(payload: dict[str, Any], source: EventSource) -> list[UniversalEvent]:
    """Dispatch to the right mapper for a payload's provenance."""
    if source == "transcript":
        return map_transcript_record(payload)
    return map_hook_payload(payload)
