"""Tests for search, charts, analytics, export and session filters."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.shared.events import EventType, UniversalEvent
from backend.shared.timeutil import utcnow
from backend.telemetry.ingestion import persist_events


@pytest.fixture
def client(temp_home):
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def seeded(temp_home):
    """Two agents, two days, files/commands/prompts/tests/commits."""
    now = utcnow()

    def evt(sid, agent, event, minutes_ago, **kwargs):
        return UniversalEvent(
            session_id=sid,
            timestamp=now - timedelta(minutes=minutes_ago),
            agent=agent,
            event=event,
            **kwargs,
        )

    persist_events(
        [
            evt("sess-a", "claude", EventType.SESSION_STARTED, 300),
            evt("sess-a", "claude", EventType.PROMPT_SUBMITTED, 290,
                metadata={"length": 250}),
            evt("sess-a", "claude", EventType.PROMPT_SUBMITTED, 280,
                metadata={"length": 12}),
            evt("sess-a", "claude", EventType.FILE_MODIFIED, 270,
                file="backend/auth.py", metadata={"lines_added": 5, "lines_removed": 1}),
            evt("sess-a", "claude", EventType.TERMINAL_COMMAND, 260,
                metadata={"command": "pytest", "exit_code": 0}),
            evt("sess-a", "claude", EventType.TEST_PASSED, 260,
                metadata={"command": "pytest"}),
            evt("sess-a", "claude", EventType.TERMINAL_COMMAND, 250,
                metadata={"command": "git commit -m x", "exit_code": 0}),
            evt("sess-a", "claude", EventType.GIT_COMMIT, 250,
                metadata={"message": None}),
            evt("sess-a", "claude", EventType.TERMINAL_COMMAND, 240,
                metadata={"command": "npm run build", "exit_code": 1}),
            evt("sess-a", "claude", EventType.SESSION_ENDED, 200),
            evt("sess-b", "opencode", EventType.SESSION_STARTED, 1500),
            evt("sess-b", "opencode", EventType.PROMPT_SUBMITTED, 1490,
                metadata={"length": 60}),
            evt("sess-b", "opencode", EventType.FILE_MODIFIED, 1480,
                file="backend/auth.py", metadata={"lines_added": 2, "lines_removed": 0}),
            evt("sess-b", "opencode", EventType.SESSION_ENDED, 1400),
        ]
    )
    return ("sess-a", "sess-b")


# -- /search ---------------------------------------------------------------


def test_search_files(client, seeded):
    body = client.get("/search", params={"q": "auth", "scope": "files"}).json()
    assert body["query"] == "auth"
    assert body["files"] == ["backend/auth.py"]
    assert body["commands"] == []
    assert body["sessions"] == []


def test_search_commands_and_sessions(client, seeded):
    body = client.get("/search", params={"q": "pytest"}).json()
    assert len(body["commands"]) == 1
    assert body["commands"][0]["command"] == "pytest"
    assert body["commands"][0]["exit_code"] == 0

    body = client.get("/search", params={"q": "sess-a", "scope": "sessions"}).json()
    assert [s["id"] for s in body["sessions"]] == ["sess-a"]


def test_search_empty_query_returns_empties(client, seeded):
    body = client.get("/search", params={"q": "   "}).json()
    assert body == {"query": "", "files": [], "commands": [], "sessions": []}


def test_search_unknown_scope_ignored(client, seeded):
    body = client.get("/search", params={"q": "auth", "scope": "nope"}).json()
    assert body["files"] == []


# -- /charts ---------------------------------------------------------------


def test_charts_7d_shape(client, seeded):
    body = client.get("/charts").json()
    assert body["range"] == "7d"
    assert len(body["points"]) == 7
    today = datetime.now().astimezone().date().isoformat()
    point = next(p for p in body["points"] if p["date"] == today)
    assert point["sessions"] >= 1
    assert point["seconds"] > 0


def test_charts_bad_range_400(client, seeded):
    assert client.get("/charts", params={"range": "year"}).status_code == 400


# -- /analytics ------------------------------------------------------------


def test_prompt_stats(client, seeded):
    body = client.get("/analytics/prompts").json()
    assert body["count"] == 3
    assert body["avg_length"] == round((250 + 12 + 60) / 3, 2)
    assert body["max_length"] == 250
    assert body["long_count"] == 1
    assert body["short_count"] == 1
    assert len(body["per_day"]) == 2


def test_prompt_stats_empty(client):
    body = client.get("/analytics/prompts").json()
    assert body["count"] == 0


def test_command_stats(client, seeded):
    body = client.get("/analytics/commands").json()
    assert body["total"] == 3
    assert body["failed"] == 1
    assert body["fail_rate"] == round(1 / 3, 4)
    assert body["git_count"] == 1
    assert body["build_count"] == 1
    top = {t["command"]: t["count"] for t in body["top"]}
    assert top["pytest"] == 1


# -- /export ---------------------------------------------------------------


def test_export_json_sessions(client, seeded):
    response = client.get("/export", params={"table": "sessions", "format": "json"})
    assert response.status_code == 200
    body = response.json()
    assert body["table"] == "sessions"
    assert {r["id"] for r in body["rows"]} == {"sess-a", "sess-b"}
    assert "attachment" in response.headers["content-disposition"]


def test_export_csv_commands(client, seeded):
    response = client.get("/export", params={"table": "commands", "format": "csv"})
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    lines = response.text.strip().splitlines()
    assert lines[0] == "session_id,command,timestamp,exit_code"
    assert len(lines) == 4  # header + 3 commands


def test_export_bad_params_400(client, seeded):
    assert client.get("/export", params={"table": "nope"}).status_code == 400
    assert client.get("/export", params={"format": "xml"}).status_code == 400


# -- /sessions filters -----------------------------------------------------


def test_sessions_agent_filter(client, seeded):
    body = client.get("/sessions", params={"agent": "opencode"}).json()
    assert [s["id"] for s in body["sessions"]] == ["sess-b"]
    body = client.get("/sessions", params={"agent": "nobody"}).json()
    assert body["sessions"] == []


def test_sessions_date_filter(client, seeded):
    today = datetime.now().astimezone().date().isoformat()
    yesterday = (datetime.now().astimezone().date() - timedelta(days=1)).isoformat()
    body = client.get("/sessions", params={"date": today}).json()
    assert {s["id"] for s in body["sessions"]} == {"sess-a"}
    body = client.get("/sessions", params={"date": yesterday}).json()
    assert {s["id"] for s in body["sessions"]} == {"sess-b"}
    body = client.get("/sessions", params={"date": "2000-01-01"}).json()
    assert body["sessions"] == []


def test_sessions_bad_date_400(client, seeded):
    assert client.get("/sessions", params={"date": "yesterday"}).status_code == 400
