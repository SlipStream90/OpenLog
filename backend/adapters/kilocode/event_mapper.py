"""Kilo Code payload -> Universal Event mapping.

Kilo Code (like Roo/Cline) emits VS Code extension events. Shapes are
[UNVERIFIED] — we probe broadly.

Kilo Code tool names observed: read_file, write_to_file, replace_in_file,
execute_command, search_files, list_files, ask_followup_question etc.
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
AGENT_NAME = "kilocode"

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "session_id": ("session_id", "sessionId", "taskId", "task_id", "id", "sid", "instanceId"),
    "hook_event_name": ("hook_event_name", "hookEventName", "event", "type", "event_type", "action", "kind"),
    "tool_name": ("tool_name", "toolName", "tool", "name", "function", "command_name", "toolName"),
    "tool_input": ("tool_input", "toolInput", "input", "parameters", "args", "arguments", "payload", "params"),
    "tool_response": ("tool_response", "toolResponse", "output", "result", "response", "return", "content"),
    "timestamp": ("timestamp", "time", "created_at", "createdAt", "_received_at", "ts", "date"),
    "prompt": ("prompt", "user_prompt", "userPrompt", "message", "content", "text", "query", "task", "userMessage"),
    "file_path": ("file_path", "filePath", "path", "filepath", "file", "filename", "absolutePath"),
    "command": ("command", "cmd", "commandLine", "execute_command"),
    "cwd": ("cwd", "workingDirectory", "working_directory", "directory", "workdir", "workspace"),
    "model": ("model", "modelName", "model_name", "apiModel", "provider", "modelId"),
    "usage": ("usage", "token_usage", "tokenUsage", "tokens", "usage_info", "tokenCount"),
    "exit_code": ("exit_code", "exitCode", "returncode", "status", "code"),
}


probe = make_probe(FIELD_ALIASES)


READ_TOOLS = frozenset({
    "read_file", "readFile", "Read", "read", "view_file", "list_files", "listFiles",
    "search_files", "searchFiles", "grep", "glob", "open_file",
})
WRITE_TOOLS = frozenset({
    "write_to_file", "writeToFile", "Write", "write", "replace_in_file", "replaceInFile",
    "edit", "apply_diff", "applyDiff", "create_file", "MultiEdit", "Update",
})
SHELL_TOOLS = frozenset({
    "execute_command", "executeCommand", "Bash", "bash", "Shell", "run", "command", "exec",
})

_TEST_PATTERN = re.compile(r"\b(pytest|jest|vitest|mocha|unittest|go\s+test|cargo\s+test|npm\s+(run\s+)?test|yarn\s+test|pnpm\s+test|rspec|phpunit|dotnet\s+test)\b", re.IGNORECASE)
_BUILD_PATTERN = re.compile(r"\b(npm\s+run\s+build|yarn\s+build|pnpm\s+build|make\b|cargo\s+build|go\s+build|docker\s+build|gradle\s+build|mvn\s+(package|install)|tsc\b|webpack\b|vite\s+build)\b", re.IGNORECASE)
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
    if prompt is None and payload.get("task"):
        prompt = payload.get("task")
    length = len(prompt) if isinstance(prompt, str) else 0
    return [build(EventType.PROMPT_SUBMITTED, metadata={"length": length})]


def _map_tool_use_hook(payload: dict[str, Any], build, cwd, normalized_hook: str) -> list[UniversalEvent]:
    return _map_tool_use(payload, normalized_hook, cwd, build)


def _map_unknown_hook(payload: dict[str, Any], hook_name: str, build, cwd) -> list[UniversalEvent]:
    logger.debug("Dropping kilocode hook %r", hook_name)
    return []


def _resolve_normalized_hook(normalized: str) -> str | None:
    """Map normalized hook name to canonical handler key."""
    if normalized in ("sessionstart", "sessionstarted", "taskstart", "start", "init", "create"):
        return "sessionstart"
    if normalized in ("sessionend", "sessionended", "taskend", "stop", "end", "finish", "complete", "taskcompleted"):
        return "sessionend"
    if normalized in ("userpromptsubmit", "prompt", "userprompt", "chatmessage", "message", "promptsubmit", "ask", "askfollowup", "userinput", "taskcreated"):
        return "userpromptsubmit"
    if normalized in ("pretooluse", "toolbefore", "toolstart", "beforetool"):
        return "pretooluse"
    if normalized in ("posttooluse", "toolafter", "toolend", "aftertool", "toolresult"):
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
        return []
    hook_name = probe(payload, "hook_event_name")
    if isinstance(hook_name, dict):
        hook_name = hook_name.get("type") or hook_name.get("event") or ""
    if not isinstance(hook_name, str) or not hook_name:
        if probe(payload, "tool_name"):
            hook_name = "PostToolUse" if probe(payload, "tool_response") else "PreToolUse"
        elif probe(payload, "prompt") or payload.get("task"):
            hook_name = "UserPromptSubmit"
        else:
            logger.debug("KiloCode payload no hook name; skipping")
            return []
    session_id = probe(payload, "session_id")
    session_id = str(session_id) if session_id else None
    received = payload.get("_received_at")
    timestamp = parse_timestamp(probe(payload, "timestamp"), default=parse_timestamp(received) if received else utcnow())
    cwd = probe(payload, "cwd")

    def build(event: EventType, *, file: str | None = None, metadata: dict[str, Any] | None = None) -> UniversalEvent:
        return UniversalEvent(session_id=session_id or "", timestamp=timestamp, agent=AGENT_NAME, event=event, model=None, file=file, metadata=metadata or {}, source="hook")

    normalized = hook_name.strip().lower().replace("_", "").replace(".", "").replace("-", "")

    handler_key = _resolve_normalized_hook(normalized)
    if handler_key and handler_key in _HOOK_DISPATCH:
        return _HOOK_DISPATCH[handler_key](payload, build, cwd)

    # Attempt tool mapping even for unknown hook names that carry a tool
    if probe(payload, "tool_name"):
        is_post = probe(payload, "tool_response") is not None
        mapped = _map_tool_use(payload, "posttooluse" if is_post else "pretooluse", cwd, build)
        if mapped:
            return mapped

    return _map_unknown_hook(payload, hook_name, build, cwd)


def _map_tool_use(payload: dict[str, Any], normalized_hook: str, cwd: Any, build) -> list[UniversalEvent]:
    tool_name = probe(payload, "tool_name")
    if not isinstance(tool_name, str):
        return []
    tool_clean = tool_name.split(":")[-1].split("/")[-1]
    tool_input = probe(payload, "tool_input") or {}
    if not isinstance(tool_input, dict):
        # kilocode sometimes puts params directly on payload
        if isinstance(payload.get("params"), dict):
            tool_input = payload["params"]
        else:
            tool_input = {}
    is_post = normalized_hook == "posttooluse"
    if tool_clean in READ_TOOLS and not is_post:
        file = _relative_file(probe(tool_input, "file_path") or probe(payload, "file_path"), cwd)
        if file is None:
            return []
        return [build(EventType.FILE_OPENED, file=file)]
    if tool_clean in WRITE_TOOLS and is_post:
        file = _relative_file(probe(tool_input, "file_path") or probe(payload, "file_path"), cwd)
        if file is None:
            return []
        added, removed = _estimate_line_delta(tool_input)
        return [build(EventType.FILE_MODIFIED, file=file, metadata={"lines_added": added, "lines_removed": removed})]
    if tool_clean in SHELL_TOOLS and is_post:
        return _map_shell_command(payload, tool_input, build)
    if is_post and probe(tool_input, "command"):
        return _map_shell_command(payload, tool_input, build)
    return []


def _map_shell_command(payload: dict[str, Any], tool_input: dict[str, Any], build) -> list[UniversalEvent]:
    command = probe(tool_input, "command")
    if not isinstance(command, str) or not command.strip():
        command = probe(payload, "command") or ""
        if not isinstance(command, str) or not command.strip():
            return []
    # Redact secrets before anything is stored: PRD section 21.
    command = sanitize_command(command.strip()) or ""
    response = probe(payload, "tool_response")
    exit_code = None
    if isinstance(response, dict):
        exit_code = _coerce_int(probe(response, "exit_code"))
    events = [build(EventType.TERMINAL_COMMAND, metadata={"command": command, "exit_code": exit_code})]
    framework = detect_test_framework(command)
    if framework is not None:
        meta = {"command": command, "framework": framework}
        if exit_code is None:
            events.append(build(EventType.TEST_EXECUTED, metadata=meta))
        elif exit_code == 0:
            events.append(build(EventType.TEST_PASSED, metadata=meta))
        else:
            events.append(build(EventType.TEST_FAILED, metadata=meta))
        return events
    if _GIT_COMMIT_PATTERN.search(command):
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
# (imported above, including its unified-diff branch); `_parse_usage` is
# `backend.shared.mapping.parse_usage`.


def map_transcript_record(record: dict[str, Any]) -> list[UniversalEvent]:
    session_id = probe(record, "session_id") or record.get("taskId") or record.get("id")
    if not session_id:
        return []
    entry_type = record.get("type") or record.get("role") or record.get("event")
    message = record.get("message") or {}
    if not isinstance(message, dict):
        message = {}
    model = probe(message, "model") or probe(record, "model")
    usage = probe(message, "usage") or probe(record, "usage")
    if entry_type not in ("assistant", "response", "ai", "agent", "kilocode"):
        if not isinstance(usage, dict) and model is None:
            return []
        if entry_type not in (None, "assistant", "response", "ai"):
            # unknown type without usage/model — skip
            if entry_type is not None and isinstance(usage, dict):
                pass
            elif entry_type is not None:
                return []
    if not isinstance(usage, dict) and model is None:
        return []

    token_count, input_tokens, output_tokens = _parse_usage(usage)

    timestamp = parse_timestamp(probe(record, "timestamp"))
    return [UniversalEvent(session_id=str(session_id), timestamp=timestamp, agent=AGENT_NAME, event=EventType.RESPONSE_RECEIVED, model=str(model) if model else None, file=None, metadata={"token_count": token_count, "model": str(model) if model else None, "input_tokens": input_tokens, "output_tokens": output_tokens}, source="transcript")]


def map_payload(payload: dict[str, Any], source: EventSource) -> list[UniversalEvent]:
    if source == "transcript":
        return map_transcript_record(payload)
    return map_hook_payload(payload)
