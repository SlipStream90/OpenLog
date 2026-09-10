"""OpenCode raw payload -> Universal Event mapping.

Probing strategy mirrors `backend/adapters/claude/event_mapper.py` but tuned
for OpenCode's vocabulary. Field names are [UNVERIFIED] — probed broadly.
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
AGENT_NAME = "opencode"

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "session_id": ("session_id", "sessionId", "sessionID", "session", "id", "sid"),
    "hook_event_name": ("hook_event_name", "hookEventName", "hook_event", "event", "type", "event_type", "eventType", "action"),
    "tool_name": ("tool_name", "toolName", "tool", "name", "function", "command_name"),
    "tool_input": ("tool_input", "toolInput", "input", "parameters", "args", "arguments", "payload"),
    "tool_response": ("tool_response", "toolResponse", "output", "result", "response", "return"),
    "timestamp": ("timestamp", "time", "created_at", "createdAt", "_received_at", "ts"),
    "prompt": ("prompt", "user_prompt", "userPrompt", "message", "content", "text", "query"),
    "file_path": ("file_path", "filePath", "path", "filepath", "file", "filename"),
    "command": ("command", "cmd", "bash_command", "shell_command"),
    "cwd": ("cwd", "workingDirectory", "working_directory", "directory", "workdir"),
    "model": ("model", "modelName", "model_name", "llm", "provider"),
    "usage": ("usage", "token_usage", "tokenUsage", "tokens", "usage_info"),
    "exit_code": ("exit_code", "exitCode", "returncode", "status", "code", "exitStatus"),
}


probe = make_probe(FIELD_ALIASES)


# OpenCode tool vocab — intentionally broad; opencode tools vary by provider
READ_TOOLS = frozenset({
    "Read", "read", "read_file", "readFile", "View", "view", "cat", "open", "glob", "Grep", "grep",
    "NotebookRead", "codebase_search", "search",
})
WRITE_TOOLS = frozenset({
    "Edit", "edit", "edit_file", "Write", "write", "write_file", "writeFile", "create", "create_file",
    "MultiEdit", "multiedit", "apply_patch", "str_replace", "Update", "NoteBookEdit",
})
SHELL_TOOLS = frozenset({
    "Bash", "bash", "Shell", "shell", "run", "command", "execute", "exec", "terminal", "BashOutput",
})

TOOL_VOCAB = ToolVocabulary(read=READ_TOOLS, write=WRITE_TOOLS, shell=SHELL_TOOLS)

_TEST_PATTERN = re.compile(
    r"\b(pytest|jest|vitest|mocha|unittest|go\s+test|cargo\s+test|npm\s+(run\s+)?test|"
    r"yarn\s+test|pnpm\s+test|rspec|phpunit|dotnet\s+test|gradle\s+test|mvn\s+test|opencode\s+test)\b",
    re.IGNORECASE,
)
_BUILD_PATTERN = re.compile(
    r"\b(npm\s+run\s+build|yarn\s+build|pnpm\s+build|make\b|cargo\s+build|go\s+build|"
    r"docker\s+build|gradle\s+build|mvn\s+(package|install)|tsc\b|webpack\b|vite\s+build|opencode\s+build)\b",
    re.IGNORECASE,
)
_GIT_COMMIT_PATTERN = re.compile(r"\bgit\s+(-[^\s]+\s+)*commit\b", re.IGNORECASE)


def detect_test_framework(command: str) -> str | None:
    return detect_framework(command, _TEST_PATTERN)


# --- Hook dispatch helpers ---

def _map_session_start(payload: dict[str, Any], build, cwd) -> list[UniversalEvent]:
    return [build(EventType.SESSION_STARTED)]


def _map_session_end(payload: dict[str, Any], build, cwd) -> list[UniversalEvent]:
    return [build(EventType.SESSION_ENDED)]


def _map_prompt_submit(payload: dict[str, Any], build, cwd) -> list[UniversalEvent]:
    prompt = probe(payload, "prompt")
    length = len(prompt) if isinstance(prompt, str) else 0
    # also handle nested message.content
    if length == 0 and isinstance(payload.get("message"), dict):
        c = payload["message"].get("content") or payload["message"].get("text")
        if isinstance(c, str):
            length = len(c)
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
    logger.debug("Dropping unmapped opencode event %r", hook_name)
    return []


def _resolve_normalized_hook(normalized: str) -> str | None:
    """Map normalized hook name to canonical handler key."""
    if normalized in ("sessionstart", "sessionstarted", "start", "init", "sessioncreate"):
        return "sessionstart"
    if normalized in ("sessionend", "sessionended", "stop", "end", "sessionstop", "finish", "complete"):
        return "sessionend"
    if normalized in ("userpromptsubmit", "prompt", "userprompt", "chatmessage", "message", "promptsubmit", "userinput"):
        return "userpromptsubmit"
    if normalized in ("pretooluse", "toolbefore", "toolstart", "beforetool", "pretool"):
        return "pretooluse"
    if normalized in ("posttooluse", "toolafter", "toolend", "aftertool", "posttool", "toolresult"):
        return "posttooluse"
    if normalized in ("tooluse", "toolcall", "tool", "action", "functioncall"):
        return "tooluse"
    if normalized in ("notification",):
        return "notification"
    return None


_HOOK_DISPATCH: dict[str, callable] = {
    "sessionstart": _map_session_start,
    "sessionend": _map_session_end,
    "userpromptsubmit": _map_prompt_submit,
    "pretooluse": lambda p, b, c: _map_tool_use_hook(p, b, c, "pretooluse"),
    "posttooluse": lambda p, b, c: _map_tool_use_hook(p, b, c, "posttooluse"),
    "tooluse": lambda p, b, c: _map_tool_use_hook(p, b, c, "tooluse"),
    "notification": lambda p, b, c: _map_unknown_hook(p, "notification", b, c),
}


def map_hook_payload(payload: dict[str, Any]) -> list[UniversalEvent]:
    if payload.get("_unparseable"):
        logger.debug("Skipping unparseable opencode hook payload")
        return []

    hook_name = probe(payload, "hook_event_name")
    if isinstance(hook_name, dict):
        # Some opencode payloads nest event name
        hook_name = hook_name.get("type") or hook_name.get("event") or ""
    if not isinstance(hook_name, str) or not hook_name:
        # Fallback: infer from tool presence
        if probe(payload, "tool_name"):
            hook_name = "PostToolUse" if probe(payload, "tool_response") else "PreToolUse"
        else:
            logger.debug("OpenCode payload with no hook name; skipping")
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


# `_estimate_line_delta` is `backend.shared.mapping.estimate_line_delta`
# (imported above); `_parse_usage` is `backend.shared.mapping.parse_usage`.


def map_transcript_record(record: dict[str, Any]) -> list[UniversalEvent]:
    session_id = probe(record, "session_id")
    if not session_id:
        # opencode may use "id" for session
        session_id = record.get("id") or record.get("session")
    if not session_id:
        return []
    entry_type = record.get("type") or record.get("role") or record.get("event")
    message = record.get("message") or {}
    if not isinstance(message, dict):
        message = {}
    model = probe(message, "model") or probe(record, "model")
    usage = probe(message, "usage") or probe(record, "usage")

    if entry_type not in ("assistant", "response", "ai", "agent", "opencode"):
        # transcript may be generic; if usage present, treat as response
        if not isinstance(usage, dict) and model is None:
            return []
        if entry_type is not None and entry_type not in ("assistant", "response", "ai"):
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
    if source == "transcript":
        return map_transcript_record(payload)
    return map_hook_payload(payload)
