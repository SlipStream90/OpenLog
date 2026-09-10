"""Shared mapping primitives for the per-agent event mappers.

The three adapters (claude/opencode/kilocode) each keep their own
`FIELD_ALIASES` and tool vocabulary -- those differ per agent by design (PRD
section 18) and stay in the adapter modules. Everything else about turning a
raw payload into a `UniversalEvent` is identical, so it lives here: field
probing, int coercion, cwd-relative paths, edit line-delta estimation, token
usage parsing, and test-framework detection.

Key-name coverage is the union of what the agents emit (e.g. `old_text` from
opencode alongside `old_string` from Claude). A union key can only fire when
the payload actually carries that field, so no agent's behavior changes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.shared.events import EventType, UniversalEvent
from backend.shared.sanitize import sanitize_command
from backend.shared.timeutil import parse_timestamp, utcnow

logger = logging.getLogger(__name__)

#: Extra key spellings seen across agents, beyond any single adapter's table.
OLD_TEXT_KEYS = ("old_string", "oldString", "old_text", "oldText")
NEW_TEXT_KEYS = ("new_string", "newString", "new_text", "newText")
CONTENT_KEYS = ("content", "text", "file_content", "diff")
USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "inputTokens",
    "outputTokens",
    "total_tokens",
    "totalTokens",
)
_INPUT_SIDE_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "inputTokens",
)


def make_probe(aliases: dict[str, tuple[str, ...]]):
    """Build the `probe(payload, logical, default)` function for one agent.

    Every field is looked up under several plausible names (ADR-009); a field
    found under none of them becomes `default` with a debug log rather than a
    `KeyError`, so a wrong schema guess degrades one field to null instead of
    crashing ingestion.
    """

    def probe(payload: dict[str, Any], logical: str, default: Any = None) -> Any:
        for alias in aliases.get(logical, (logical,)):
            if alias in payload and payload[alias] is not None:
                return payload[alias]
        logger.debug(
            "No value for logical field %r in payload keys %s",
            logical,
            list(payload),
        )
        return default

    return probe


def coerce_int(value: Any) -> int | None:
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


def relative_file(path: Any, cwd: Any) -> str | None:
    """Render a file path relative to the session's working directory.

    Absolute paths leak the developer's home directory layout into the
    database and make the same file look like two different files across
    machines.
    """
    if not isinstance(path, str) or not path.strip():
        return None
    text = path.strip().replace("\\", "/")
    if isinstance(cwd, str) and cwd.strip():
        base = cwd.strip().replace("\\", "/").rstrip("/")
        if base and text.lower().startswith(base.lower() + "/"):
            return text[len(base) + 1 :]
    return text


def detect_framework(command: str, pattern: re.Pattern[str]) -> str | None:
    """Best-effort test-framework label for a command. `None` when unclear.

    Explicitly a heuristic: returning `None` is a perfectly good answer --
    guessing a framework would put a fabricated value into the record.
    """
    match = pattern.search(command or "")
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(0)).strip().lower()


def _first_str(tool_input: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return None


def estimate_line_delta(tool_input: dict[str, Any]) -> tuple[int, int]:
    """Estimate (added, removed) lines from an edit tool's input.

    Best-effort only: for an Edit we can diff old vs new string; for a Write
    of a new file we know only the line count. Where nothing is derivable we
    return (0, 0) rather than a guess.
    """
    old = _first_str(tool_input, OLD_TEXT_KEYS)
    new = _first_str(tool_input, NEW_TEXT_KEYS)
    if old is None and new is None:
        # Some agents (Kilo Code) emit only a `diff` (unified or replacement
        # text): treat it as the new text.
        diff = tool_input.get("diff")
        if isinstance(diff, str):
            new = diff
    if old is not None or new is not None:
        if isinstance(new, str) and new.startswith("@@"):
            # Unified diff text: count +/- lines rather than diffing strings.
            added = sum(
                1 for line in new.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            )
            removed = sum(
                1 for line in new.splitlines()
                if line.startswith("-") and not line.startswith("---")
            )
            return added, removed
        old_lines = len(old.splitlines()) if old is not None else 0
        new_lines = len(new.splitlines()) if new is not None else 0
        return max(new_lines - old_lines, 0), max(old_lines - new_lines, 0)

    content = _first_str(tool_input, CONTENT_KEYS)
    if content is not None:
        return len(content.splitlines()), 0

    edits = tool_input.get("edits")
    if isinstance(edits, list):
        added = removed = 0
        for edit in edits:
            if isinstance(edit, dict):
                a, r = estimate_line_delta(edit)
                added += a
                removed += r
        return added, removed

    return 0, 0


def parse_usage(usage: dict[str, Any]) -> tuple[int | None, int, int]:
    """Parse a token usage dict into (token_count, input_tokens, output_tokens).

    Returns (None, 0, 0) when `usage` is not a valid dict. Cache reads/writes
    are billed against the input side.
    """
    if not isinstance(usage, dict):
        return None, 0, 0

    counts = {key: coerce_int(usage.get(key)) for key in USAGE_KEYS}
    present = [v for v in counts.values() if v is not None]
    token_count: int | None = sum(present) if present else None
    input_tokens = sum(counts[k] or 0 for k in _INPUT_SIDE_KEYS)
    output_tokens = counts.get("output_tokens") or counts.get("outputTokens") or 0
    # Some agents report only a total: accept it as the count, never invent a split.
    if token_count is None:
        token_count = counts.get("total_tokens") or counts.get("totalTokens")
    return token_count, input_tokens, output_tokens


@dataclass(frozen=True)
class HookContext:
    """The shared preamble of every `map_hook_payload`: identity + time + cwd."""

    session_id: str | None
    timestamp: datetime
    cwd: Any


def hook_context(payload: dict[str, Any], probe, agent_name: str = "") -> HookContext | None:
    """Extract session/time/cwd from a hook payload.

    Returns `None` for `_unparseable` envelopes (the caller returns `[]`).
    Never raises on missing fields: absent values degrade to nulls (ADR-009).
    """
    if payload.get("_unparseable"):
        logger.debug("Skipping unparseable %s hook payload", agent_name or "agent")
        return None
    session_id = probe(payload, "session_id")
    session_id = str(session_id) if session_id else None
    received = payload.get("_received_at")
    timestamp = parse_timestamp(
        probe(payload, "timestamp"),
        default=parse_timestamp(received) if received else utcnow(),
    )
    return HookContext(
        session_id=session_id, timestamp=timestamp, cwd=probe(payload, "cwd")
    )


def build_event(
    ctx: HookContext,
    agent_name: str,
    event: EventType,
    *,
    file: str | None = None,
    metadata: dict[str, Any] | None = None,
    model: str | None = None,
) -> UniversalEvent:
    """One `UniversalEvent` from a context. Hooks never expose the model, so
    hook call sites leave it `None`; transcripts enrich it separately."""
    return UniversalEvent(
        session_id=ctx.session_id or "",
        timestamp=ctx.timestamp,
        agent=agent_name,
        event=event,
        model=model,
        file=file,
        metadata=metadata or {},
        source="hook",
    )


def make_build(ctx: HookContext, agent_name: str):
    """Build the per-payload `build(event, ...)` closure mappers pass into
    their dispatch tables. One line at each call site instead of three
    identical closures per adapter."""

    def build(
        event: EventType,
        *,
        file: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UniversalEvent:
        return build_event(ctx, agent_name, event, file=file, metadata=metadata)

    return build


def dispatch_hook_payload(
    payload: dict[str, Any],
    hook_name: str,
    build,
    cwd: Any,
    *,
    vocab: ToolVocabulary,
    probe,
    test_pattern,
    build_pattern,
    git_pattern,
    resolve_hook,
    dispatch: dict,
    unknown_hook,
) -> list[UniversalEvent]:
    """Route a named hook through an agent's dispatch table.

    The table, the name normalizer and the unknown-hook handler are the only
    per-agent inputs; normalization, tool-fallback and the call convention
    are identical everywhere. `resolve_hook` maps a normalized name to a
    dispatch-table *key* (or `None`); `unknown_hook(payload, hook_name,
    build, cwd)` handles the miss.
    """
    normalized = hook_name.strip().lower().replace("_", "").replace(".", "").replace("-", "")
    handler_key = resolve_hook(normalized)
    if handler_key and handler_key in dispatch:
        return dispatch[handler_key](payload, build, cwd)
    # Attempt tool mapping even for unknown hook names that carry a tool.
    if probe(payload, "tool_name"):
        is_post = probe(payload, "tool_response") is not None
        mapped = map_tool_use_event(
            payload,
            "posttooluse" if is_post else "pretooluse",
            cwd,
            build,
            vocab=vocab,
            probe=probe,
            test_pattern=test_pattern,
            build_pattern=build_pattern,
            git_pattern=git_pattern,
        )
        if mapped:
            return mapped
    return unknown_hook(payload, hook_name, build, cwd)


def transcript_response(
    *,
    session_id: Any,
    record_timestamp: Any,
    agent_name: str,
    model: Any,
    usage: Any,
) -> list[UniversalEvent]:
    """One `RESPONSE_RECEIVED` event from a transcript record's model+usage.

    Callers keep their own entry-type gating (which record kinds count as a
    response differs per agent); everything after the gate is identical.
    Message *text* is never extracted (PRD section 21).
    """
    token_count, input_tokens, output_tokens = parse_usage(usage)
    return [
        UniversalEvent(
            session_id=str(session_id),
            timestamp=parse_timestamp(record_timestamp),
            agent=agent_name,
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


@dataclass(frozen=True)
class ToolVocabulary:
    """Per-agent tool names, grouped by observable effect.

    The grouping differs per agent by design (PRD section 18) and each
    adapter keeps its own sets; the *mapping* from group to events is
    identical and lives in `map_tool_use_event` below.
    """

    read: frozenset = frozenset()
    write: frozenset = frozenset()
    shell: frozenset = frozenset()


def map_tool_use_event(
    payload: dict[str, Any],
    normalized_hook: str,
    cwd: Any,
    build,
    *,
    vocab: ToolVocabulary,
    probe,
    test_pattern,
    build_pattern,
    git_pattern,
) -> list[UniversalEvent]:
    """Map one tool-use payload to file/command events.

    Union semantics across agents: tool names are normalized past `a:b` /
    `a/b` prefixes (identity for plain names), `params` is accepted as a
    `tool_input` spelling, and a file path or command carried directly on the
    payload backs up the one in `tool_input`. Each leniency only converts a
    would-be drop into an event; nothing previously mapped changes shape.
    """
    tool_name = probe(payload, "tool_name")
    if not isinstance(tool_name, str):
        return []
    tool = tool_name.split(":")[-1].split("/")[-1]
    tool_input = probe(payload, "tool_input") or {}
    if not isinstance(tool_input, dict):
        params = payload.get("params")
        tool_input = params if isinstance(params, dict) else {}
    is_post = normalized_hook == "posttooluse"

    if tool in vocab.read and not is_post:
        # Reads map on pre-use: the open is the observable act.
        file = relative_file(
            probe(tool_input, "file_path") or probe(payload, "file_path"), cwd
        )
        if file is None:
            return []
        return [build(EventType.FILE_OPENED, file=file)]

    if tool in vocab.write and is_post:
        # Writes map on post-use: only a completed edit is a modification.
        file = relative_file(
            probe(tool_input, "file_path") or probe(payload, "file_path"), cwd
        )
        if file is None:
            return []
        added, removed = estimate_line_delta(tool_input)
        return [
            build(
                EventType.FILE_MODIFIED,
                file=file,
                metadata={"lines_added": added, "lines_removed": removed},
            )
        ]

    if tool in vocab.shell and is_post:
        return map_shell_command_event(
            payload,
            tool_input,
            build,
            probe=probe,
            test_pattern=test_pattern,
            build_pattern=build_pattern,
            git_pattern=git_pattern,
        )
    if is_post and probe(tool_input, "command"):
        return map_shell_command_event(
            payload,
            tool_input,
            build,
            probe=probe,
            test_pattern=test_pattern,
            build_pattern=build_pattern,
            git_pattern=git_pattern,
        )
    return []


def map_shell_command_event(
    payload: dict[str, Any],
    tool_input: dict[str, Any],
    build,
    *,
    probe,
    test_pattern,
    build_pattern,
    git_pattern,
) -> list[UniversalEvent]:
    """One shell invocation becomes TERMINAL_COMMAND plus, when recognized, a
    test/build/commit observation. The stored command is redacted (PRD 21);
    classification only matches tool names, never secret values."""
    command = probe(tool_input, "command")
    if not isinstance(command, str) or not command.strip():
        command = probe(payload, "command") or ""
        if not isinstance(command, str) or not command.strip():
            return []
    command = sanitize_command(command.strip()) or ""

    response = probe(payload, "tool_response")
    exit_code = None
    if isinstance(response, dict):
        exit_code = coerce_int(probe(response, "exit_code"))
    elif isinstance(tool_input, dict):
        exit_code = coerce_int(probe(tool_input, "exit_code"))

    events = [
        build(
            EventType.TERMINAL_COMMAND,
            metadata={"command": command, "exit_code": exit_code},
        )
    ]

    framework = detect_framework(command, test_pattern)
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

    if git_pattern.search(command):
        # Subject line only -- never the diff.
        events.append(build(EventType.GIT_COMMIT, metadata={"message": None}))
        return events

    if build_pattern.search(command):
        meta = {"command": command}
        events.append(build(EventType.BUILD_STARTED, metadata=meta))
        if exit_code is not None:
            events.append(build(EventType.BUILD_FINISHED, metadata=meta))
        return events

    return events
