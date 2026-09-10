"""Codex CLI raw payload -> Universal Event mapping.

Probing strategy mirrors the other adapters but tuned for Codex's vocabulary
(thread/turn/item naming). Field names and transcript locations are
[UNVERIFIED] -- inferred from the CLI's observable shape, not confirmed
against live docs. Every lookup degrades to null rather than raising
(ADR-009); if the real schema differs, this file is the only one that needs
to change.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.shared.events import EventSource, EventType, UniversalEvent
from backend.shared.mapping import (
    ToolVocabulary,
    make_build,
    detect_framework,
    dispatch_hook_payload,
    hook_context,
    make_probe,
    map_tool_use_event,
    transcript_response,
)

logger = logging.getLogger(__name__)
AGENT_NAME = "codex"

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "session_id": ("session_id", "sessionId", "thread_id", "threadId", "thread", "conversation_id", "conversationId", "id", "sid"),
    "hook_event_name": ("hook_event_name", "hookEventName", "event", "type", "event_type", "eventType", "action", "phase"),
    "tool_name": ("tool_name", "toolName", "tool", "name", "function", "command_name", "action_type"),
    "tool_input": ("tool_input", "toolInput", "input", "parameters", "args", "arguments", "payload", "params"),
    "tool_response": ("tool_response", "toolResponse", "output", "result", "response", "return", "observation"),
    "timestamp": ("timestamp", "time", "created_at", "createdAt", "_received_at", "ts"),
    "prompt": ("prompt", "user_prompt", "userPrompt", "message", "content", "text", "query", "input_text"),
    "file_path": ("file_path", "filePath", "path", "filepath", "file", "filename", "target_file"),
    "command": ("command", "cmd", "bash_command", "shell_command", "exec_command"),
    "cwd": ("cwd", "workingDirectory", "working_directory", "directory", "workdir"),
    "model": ("model", "modelName", "model_name", "llm"),
    "usage": ("usage", "token_usage", "tokenUsage", "tokens", "usage_info"),
    "exit_code": ("exit_code", "exitCode", "returncode", "status", "code", "exitStatus"),
}

probe = make_probe(FIELD_ALIASES)

#: Codex tool vocabulary ([UNVERIFIED] -- broad on purpose; unknown tools are
#: skipped, never misclassified).
READ_TOOLS = frozenset({
    "read", "read_file", "readFile", "view", "cat", "open", "list_files", "search", "grep",
})
WRITE_TOOLS = frozenset({
    "write", "write_file", "writeFile", "edit", "apply_patch", "create_file", "update_file",
})
SHELL_TOOLS = frozenset({
    "shell", "exec", "execute", "bash", "command", "run", "terminal",
})

TOOL_VOCAB = ToolVocabulary(read=READ_TOOLS, write=WRITE_TOOLS, shell=SHELL_TOOLS)

_TEST_PATTERN = re.compile(
    r"\b(pytest|jest|vitest|mocha|unittest|go\s+test|cargo\s+test|npm\s+(run\s+)?test|"
    r"yarn\s+test|pnpm\s+test|rspec|phpunit|dotnet\s+test)\b",
    re.IGNORECASE,
)
_BUILD_PATTERN = re.compile(
    r"\b(npm\s+run\s+build|yarn\s+build|pnpm\s+build|make\b|cargo\s+build|go\s+build|"
    r"docker\s+build|tsc\b|webpack\b|vite\s+build)\b",
    re.IGNORECASE,
)
_GIT_COMMIT_PATTERN = re.compile(r"\bgit\s+(-[^\s]+\s+)*commit\b", re.IGNORECASE)


def detect_test_framework(command: str) -> str | None:
    return detect_framework(command, _TEST_PATTERN)


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
    logger.debug("Dropping unmapped codex hook event %r", hook_name)
    return []


def _resolve_normalized_hook(normalized: str) -> str | None:
    if normalized in ("sessionstart", "sessionstarted", "threadstart", "threadstarted", "start", "init"):
        return "sessionstart"
    if normalized in ("sessionend", "sessionended", "threadend", "stop", "end", "finish", "complete"):
        return "sessionend"
    if normalized in ("userpromptsubmit", "prompt", "message", "userinput", "usermessage"):
        return "userpromptsubmit"
    if normalized in ("pretooluse", "toolstart", "beforetool", "toolcallstarted"):
        return "pretooluse"
    if normalized in ("posttooluse", "toolend", "aftertool", "toolresult", "itemcompleted"):
        return "posttooluse"
    if normalized in ("tooluse", "toolcall", "tool", "action"):
        return "tooluse"
    return None


_HOOK_DISPATCH: dict[str, callable] = {
    "sessionstart": _map_session_start,
    "sessionend": _map_session_end,
    "userpromptsubmit": _map_prompt_submit,
    "pretooluse": lambda p, b, c: _map_tool_use_hook(p, b, c, "pretooluse"),
    "posttooluse": lambda p, b, c: _map_tool_use_hook(p, b, c, "posttooluse"),
    "tooluse": lambda p, b, c: _map_tool_use_hook(p, b, c, "tooluse"),
}


def map_hook_payload(payload: dict[str, Any]) -> list[UniversalEvent]:
    if payload.get("_unparseable"):
        logger.debug("Skipping unparseable codex hook payload")
        return []

    hook_name = probe(payload, "hook_event_name")
    if isinstance(hook_name, dict):
        hook_name = hook_name.get("type") or hook_name.get("event") or ""
    if not isinstance(hook_name, str) or not hook_name:
        if probe(payload, "tool_name"):
            hook_name = "PostToolUse" if probe(payload, "tool_response") else "PreToolUse"
        else:
            logger.debug("Codex payload with no hook name; skipping")
            return []

    ctx = hook_context(payload, probe, AGENT_NAME)
    if ctx is None:
        return []

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
        resolve_hook=_resolve_normalized_hook,
        dispatch=_HOOK_DISPATCH,
        unknown_hook=_map_unknown_hook,
    )


def map_transcript_record(record: dict[str, Any]) -> list[UniversalEvent]:
    """Normalize one Codex session JSONL line.

    Transcripts supply model name and token counts; message *text* is never
    extracted (PRD section 21).
    """
    session_id = probe(record, "session_id")
    if not session_id:
        return []

    entry_type = record.get("type") or record.get("role") or record.get("event")
    message = record.get("message")
    if not isinstance(message, dict):
        message = {}

    model = probe(message, "model") or probe(record, "model")
    usage = probe(message, "usage") or probe(record, "usage")

    if entry_type not in ("assistant", "response", "agent"):
        if not isinstance(usage, dict) and model is None:
            return []
        if entry_type is not None and entry_type not in ("assistant", "response", "agent"):
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
