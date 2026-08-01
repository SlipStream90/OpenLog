"""Shared fixtures.

Every test runs against a temp `AI_OBSERVATORY_HOME`, so the suite can never
read or write the developer's real `~/.ai-observatory/` database.
"""

from __future__ import annotations

import os

import pytest

from backend.adapters.claude import pricing
from backend.database.session import init_db, reset_engine
from backend.shared import paths
from backend.telemetry.watcher_status import registry


@pytest.fixture(autouse=True)
def temp_home(tmp_path, monkeypatch):
    """Point all local storage at a temp directory for the duration of a test."""
    home = tmp_path / "ai-observatory"
    monkeypatch.setenv(paths.ENV_HOME_OVERRIDE, str(home))
    monkeypatch.setenv("CLAUDE_TRANSCRIPT_ROOT", str(tmp_path / "claude-projects"))
    monkeypatch.setenv("AI_OBSERVATORY_DISABLE_TELEMETRY", "1")

    # The engine caches its URL, so it must be dropped both before and after:
    # before, so we do not inherit a previous test's database; after, so we do
    # not leak this test's temp path into the next one.
    reset_engine()
    pricing.reset_cache()
    registry.clear()
    paths.ensure_directories()
    init_db()

    yield home

    reset_engine()
    pricing.reset_cache()
    registry.clear()


@pytest.fixture
def hook_payload():
    """A representative Claude Code hook payload.

    [UNVERIFIED] shape -- see backend/adapters/claude/event_mapper.py. These
    fixtures encode the *assumed* schema; if it turns out to differ, these are
    the values to correct, and the probing tests below cover the alternates.
    """

    def _build(**overrides):
        payload = {
            "session_id": "sess-abc123",
            "hook_event_name": "PostToolUse",
            "cwd": "/home/dev/project",
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/home/dev/project/backend/app.py",
                "old_string": "a\nb\n",
                "new_string": "a\nb\nc\nd\n",
            },
            "_received_at": 1767225600.0,
        }
        payload.update(overrides)
        return payload

    return _build
