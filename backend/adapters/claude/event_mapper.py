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


def probe(payload: dict[str, Any], logical: str, default: Any = None) -> Any:
    """Look a logical field up under any of its plausible real names.

    Returns `default` and logs at debug level when nothing matches -- never
    raises. This is the single mechanism keeping the [UNVERIFIED] schema from
    being able to crash ingestion.
    """
    for alias in FIELD_ALIASES.get(logical, (logical,)):
        if alias in payload and payload[alias] is not None:
            return payload[alias]
    logger.debug("No value for logical field %r in payload keys %s", logical, list(payload))
    return default


def _coerce_int(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.strip():
            return int(value.strip())
    except (TypeError, ValueError):
        pass
    return None


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


def detect_test_framework(command: str) -> str | None:
    """Best-effort framework label for a test command. `None` when unclear.

    Explicitly a heuristic (data_models.md section 2). Returning `None` is a
    perfectly good answer -- guessing a framework would put a fabricated value
    into the record.
    """
    match = _TEST_PATTERN.search(command or "")
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(0)).strip().lower()


def _relative_file(path: Any, cwd: Any) -> str | None:
    """Render a file path relative to the session's working directory.

    Absolute paths leak the developer's home directory layout into the database
    and make the same file look like two different files across machines.
    """
    if not isinstance(path, str) or not path.strip():
        return None
    text = path.strip().replace("\\", "/")
    if isinstance(cwd, str) and cwd.strip():
        base = cwd.strip().replace("\\", "/").rstrip("/")
        if base and text.lower().startswith(base.lower() + "/"):
            return text[len(base) + 1 :]
    return text


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

    if normalized in ("sessionstart",):
        return [build(EventType.SESSION_STARTED)]

    if normalized in ("sessionend", "stop"):
        return [build(EventType.SESSION_ENDED)]

    if normalized in ("userpromptsubmit",):
        prompt = probe(payload, "prompt")
        # LENGTH ONLY. The prompt text must never reach the database (PRD 21).
        length = len(prompt) if isinstance(prompt, str) else 0
        return [build(EventType.PROMPT_SUBMITTED, metadata={"length": length})]

    if normalized in ("pretooluse", "posttooluse"):
        return _map_tool_use(payload, normalized, cwd, build)

    if normalized in ("notification",):
        # Not one of PRD section 12's types; intentionally dropped rather than
        # forced into `warning`.
        logger.debug("Dropping unmapped hook event %r", hook_name)
        return []

    logger.debug("Dropping unmapped hook event %r", hook_name)
    return []


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
    command = command.strip()

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


def _estimate_line_delta(tool_input: dict[str, Any]) -> tuple[int, int]:
    """Estimate lines added/removed from an edit tool's input.

    Best-effort only: for an Edit we can diff old vs new string; for a Write of a
    new file we know only the line count. Where nothing is derivable we return
    (0, 0) rather than a guess.
    """
    old = tool_input.get("old_string") or tool_input.get("oldString")
    new = tool_input.get("new_string") or tool_input.get("newString")
    if isinstance(old, str) or isinstance(new, str):
        old_lines = len(old.splitlines()) if isinstance(old, str) else 0
        new_lines = len(new.splitlines()) if isinstance(new, str) else 0
        return max(new_lines - old_lines, 0), max(old_lines - new_lines, 0)

    content = tool_input.get("content")
    if isinstance(content, str):
        return len(content.splitlines()), 0

    edits = tool_input.get("edits")
    if isinstance(edits, list):
        added = removed = 0
        for edit in edits:
            if isinstance(edit, dict):
                a, r = _estimate_line_delta(edit)
                added += a
                removed += r
        return added, removed

    return 0, 0


# --------------------------------------------------------------------------
# Transcript record mapping
# --------------------------------------------------------------------------


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

    token_count = None
    input_tokens = output_tokens = 0
    if isinstance(usage, dict):
        counts = {
            key: _coerce_int(usage.get(key))
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        }
        present = [v for v in counts.values() if v is not None]
        token_count = sum(present) if present else None
        # Cache reads/writes are billed against the input side.
        input_tokens = sum(
            counts[k] or 0
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        output_tokens = counts["output_tokens"] or 0

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
