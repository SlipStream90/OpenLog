"""Deterministic productivity scoring (PRD section 15).

Scores must be explainable (every point has a reason), bounded (0-100), and
absent -- never zero -- when there is no evidence.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from backend.analytics.productivity import SessionFactors, score_session
from backend.api.main import create_app
from backend.shared.events import EventType, UniversalEvent
from backend.shared.timeutil import utcnow
from backend.telemetry.ingestion import persist_events


def test_empty_session_scores_none_not_zero():
    assert score_session(SessionFactors()) is None


def test_strong_session_scores_high_with_reasons():
    scored = score_session(
        SessionFactors(
            completed=True,
            duration_seconds=1800,
            commits=2,
            tests_passed=3,
            distinct_files=4,
            edits=5,
            prompts=3,
            avg_prompt_length=120,
        )
    )
    assert scored is not None
    assert scored.score >= 80
    assert any("completed" in r for r in scored.reasons)
    assert any("commit" in r for r in scored.reasons)


def test_abandoned_failing_session_scores_low():
    scored = score_session(
        SessionFactors(
            completed=False,
            duration_seconds=60,
            tests_failed=4,
            errors=3,
            distinct_files=1,
            edits=12,
        )
    )
    assert scored is not None
    assert scored.score <= 40
    assert any("never completed" in r for r in scored.reasons)
    assert any("repeated edit" in r for r in scored.reasons)


def test_prompt_churn_and_testless_commands_penalized():
    churn = score_session(
        SessionFactors(completed=True, prompts=10, avg_prompt_length=12)
    )
    calm = score_session(
        SessionFactors(completed=True, prompts=2, avg_prompt_length=200)
    )
    assert churn is not None and calm is not None
    assert churn.score < calm.score

    testless = score_session(SessionFactors(completed=True, commands=5))
    assert testless is not None
    assert any("no tests" in r for r in testless.reasons)


def test_score_clamps_to_zero():
    scored = score_session(
        SessionFactors(completed=False, tests_failed=50, errors=50, edits=200)
    )
    assert scored is not None
    assert scored.score == 0


def test_api_sessions_carry_scores_and_reasons(temp_home):
    now = utcnow()

    def evt(event, minutes, **kwargs):
        return UniversalEvent(
            session_id="sess-p",
            timestamp=now - timedelta(minutes=minutes),
            agent="claude",
            event=event,
            **kwargs,
        )

    persist_events(
        [
            evt(EventType.SESSION_STARTED, 30),
            evt(EventType.PROMPT_SUBMITTED, 29, metadata={"length": 100}),
            evt(EventType.TERMINAL_COMMAND, 28, metadata={"command": "pytest", "exit_code": 0}),
            evt(EventType.TEST_PASSED, 28, metadata={"command": "pytest"}),
            evt(EventType.GIT_COMMIT, 27, metadata={"message": None}),
            evt(EventType.SESSION_ENDED, 10),
        ]
    )
    with TestClient(create_app()) as client:
        row = client.get("/sessions").json()["sessions"][0]
        assert row["productivity"] is not None
        assert row["productivity"] >= 70
        assert any("completed" in r for r in row["productivity_reasons"])

        detail = client.get("/session/sess-p").json()
        assert detail["productivity"] == row["productivity"]
