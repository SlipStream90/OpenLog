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
from typing import Any

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
