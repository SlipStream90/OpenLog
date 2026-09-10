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

TOOL_VOCAB = ToolVocabulary(read=READ_TOOLS, write=WRITE_TOOLS, shell=SHELL_TOOLS)

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
