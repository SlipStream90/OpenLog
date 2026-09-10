"""API endpoint tests -- TestClient against a temp SQLite database.

Covers all five authorized endpoints, both 404 paths, and the network-disabled
regression guard recommended by ARCHITECTURE.md section 6.
"""

from __future__ import annotations

import socket
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.shared.events import EventType, UniversalEvent
from backend.shared.timeutil import utcnow
from backend.telemetry.ingestion import persist_events
from backend.telemetry.watcher_status import registry


@pytest.fixture
def client(temp_home):
    # temp_home sets AI_OBSERVATORY_DISABLE_TELEMETRY, so no watcher tasks start.
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def seeded(temp_home):
    """One complete session's worth of events, started today."""
    start = utcnow() - timedelta(hours=1)

    def evt(event, minutes, **kwargs):
        return UniversalEvent(
            session_id="sess-1",
            timestamp=start + timedelta(minutes=minutes),
            agent="claude",
            event=event,
            **kwargs,
        )

    persist_events(
        [
            evt(EventType.SESSION_STARTED, 0),
            evt(EventType.PROMPT_SUBMITTED, 1, metadata={"length": 42}),
            evt(EventType.FILE_OPENED, 2, file="auth.py"),
            evt(
                EventType.FILE_MODIFIED,
                3,
                file="middleware.py",
                metadata={"lines_added": 25, "lines_removed": 12},
            ),
            evt(
                EventType.TERMINAL_COMMAND,
                4,
                metadata={"command": "pytest", "exit_code": 0},
            ),
            evt(EventType.TEST_PASSED, 5, metadata={"command": "pytest"}),
            evt(EventType.GIT_COMMIT, 6, metadata={"message": None}),
            evt(
                EventType.RESPONSE_RECEIVED,
                7,
                model="claude-sonnet-4-5",
                metadata={"token_count": 1540},
                source="transcript",
            ),
            evt(EventType.SESSION_ENDED, 45),
        ]
    )
    return "sess-1"


# -- GET /sessions ----------------------------------------------------------


def test_sessions_empty(client):
    response = client.get("/sessions")
    assert response.status_code == 200
    assert response.json() == {"sessions": []}


def test_sessions_shape(client, seeded):
    response = client.get("/sessions")
    assert response.status_code == 200

    sessions = response.json()["sessions"]
    assert len(sessions) == 1
    row = sessions[0]
    assert row["id"] == "sess-1"
    assert row["agent"] == "claude"
    assert row["model"] == "claude-sonnet-4-5"
    assert row["file_count"] == 2
    assert row["command_count"] == 1
    assert row["token_count"] == 1540
    assert row["duration_seconds"] == pytest.approx(2700, abs=2)
    # Productivity is null, never a number, until Milestone 3.
    assert row["productivity"] is None
    assert row["start_time"].endswith("Z")


# -- GET /session/{id} ------------------------------------------------------


def test_session_detail(client, seeded):
    response = client.get(f"/session/{seeded}")
    assert response.status_code == 200

    body = response.json()
    assert body["test_pass_count"] == 1
    assert body["test_fail_count"] == 0
    assert body["commit_count"] == 1
    assert body["productivity"] is None


def test_session_detail_404(client):
    response = client.get("/session/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


# -- GET /timeline/{id} -----------------------------------------------------


def test_timeline_is_ordered_and_labelled(client, seeded):
    response = client.get(f"/timeline/{seeded}")
    assert response.status_code == 200

    body = response.json()
    assert body["session_id"] == "sess-1"
    events = body["events"]
    assert len(events) == 9

    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps)

    labels = [e["label"] for e in events]
    assert labels[0] == "Session started"
    assert "Opened auth.py" in labels
    assert "Modified middleware.py" in labels
    assert "Ran: pytest" in labels
    assert "Tests passed" in labels
    assert labels[-1] == "Session finished"


def test_timeline_404(client):
    response = client.get("/timeline/nope")
    assert response.status_code == 404


# -- GET /files -------------------------------------------------------------


def test_files_aggregate(client, seeded):
    response = client.get("/files")
    assert response.status_code == 200

    files = {f["filename"]: f for f in response.json()["files"]}
    assert set(files) == {"auth.py", "middleware.py"}
    assert files["middleware.py"]["total_additions"] == 25
    assert files["middleware.py"]["total_deletions"] == 12
    assert files["middleware.py"]["total_modifications"] == 1
    assert files["middleware.py"]["session_count"] == 1


# -- GET /stats -------------------------------------------------------------


def test_stats_shape(client, seeded):
    registry.mark_success("hook_queue_tailer")
    registry.mark_failure("transcript_poller", RuntimeError("disk gone"))

    response = client.get("/stats")
    assert response.status_code == 200

    body = response.json()
    assert body["session_count"] == 1
    assert body["files_changed_count"] == 2
    assert body["command_count"] == 1
    assert body["test_count"] == 1
    assert body["coding_time_seconds"] == pytest.approx(2700, abs=5)
    # No pricing table configured => an honest zero, flagged as unpriced.
    assert body["estimated_cost"] == 0.0
    assert body["cost_is_estimated"] is False
    # No productivity score at all -- absent, not null (PRD.md section 4).
    assert "productivity_score" not in body

    watchers = body["watchers"]
    assert watchers["hook_queue_tailer"]["status"] == "running"
    assert watchers["transcript_poller"]["status"] == "degraded"
    assert "disk gone" in watchers["transcript_poller"]["last_error"]


def test_stats_watcher_error_carries_no_traceback(client):
    """Error strings are served over HTTP; a traceback could embed source."""
    try:
        raise ValueError("boom")
    except ValueError as exc:
        registry.mark_failure("hook_queue_tailer", exc)

    body = client.get("/stats").json()
    message = body["watchers"]["hook_queue_tailer"]["last_error"]
    assert message == "ValueError: boom"
    assert "Traceback" not in message
    assert ".py" not in message


# -- Scope guard ------------------------------------------------------------


@pytest.mark.parametrize("path", ["/recommendations"])
def test_out_of_scope_endpoints_are_not_implemented(client, path):
    """Milestone 3 endpoints must not have crept in.

    /charts and /search used to be on this list; they are implemented now
    (read-only aggregations over existing tables) and covered in
    test_new_endpoints.py.
    """
    assert client.get(path).status_code == 404


# -- CORS -------------------------------------------------------------------


def test_cors_allows_dashboard_origin(client):
    response = client.get("/sessions", headers={"Origin": "http://localhost:3000"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_foreign_origin(client):
    """Never `*` -- nothing off this machine may read the telemetry database."""
    response = client.get("/sessions", headers={"Origin": "https://evil.example.com"})
    assert response.headers.get("access-control-allow-origin") != "*"
    assert response.headers.get("access-control-allow-origin") != "https://evil.example.com"


# -- Network-disabled regression guard (ARCHITECTURE.md section 6) ----------


def test_no_outbound_network_connection_is_attempted(temp_home, seeded, monkeypatch):
    """The product must keep working with the network disabled (PRD section 21).

    Rather than trusting that no module imports an HTTP client, this asserts it:
    any connect() to a non-loopback address during a full pass over every
    endpoint fails the test.
    """
    attempted: list[object] = []
    real_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost", "testserver"):
            attempted.append(address)
            raise AssertionError(f"outbound connection attempted to {address!r}")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    with TestClient(create_app()) as guarded_client:
        for path in (
            "/sessions",
            f"/session/{seeded}",
            f"/timeline/{seeded}",
            "/files",
            "/stats",
            "/search?q=test",
            "/charts",
            "/analytics/prompts",
            "/analytics/commands",
            "/export?table=sessions&format=json",
        ):
            assert guarded_client.get(path).status_code == 200

    assert attempted == []
