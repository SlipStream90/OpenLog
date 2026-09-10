"""Recommendation rules (PRD section 16) -- pure rules plus the endpoint."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from backend.analytics.recommendations import (
    RecommendationContext,
    recommend,
)
from backend.api.main import create_app
from backend.shared.events import EventType, UniversalEvent
from backend.shared.timeutil import utcnow
from backend.telemetry.ingestion import persist_events


def test_no_sessions_no_recommendations():
    assert recommend(RecommendationContext()) == []


def test_hot_file_rule_fires_once():
    ctx = RecommendationContext(
        total_sessions=5,
        file_session_counts=(("auth.py", 4), ("other.py", 3)),
        priced=True,
    )
    recs = recommend(ctx)
    hot = [r for r in recs if r.rule_id == "hot-file"]
    assert len(hot) == 1
    assert "auth.py" in hot[0].message
    assert hot[0].metric == {"filename": "auth.py", "sessions": 4}


def test_short_prompts_and_untested_rules():
    ctx = RecommendationContext(
        total_sessions=4,
        prompt_count=6,
        avg_prompt_length=22,
        sessions_with_commands=4,
        sessions_with_tests=1,
        priced=True,
    )
    ids = {r.rule_id for r in recommend(ctx)}
    assert {"short-prompts", "untested-sessions"} <= ids


def test_interruptions_and_unpriced_rules():
    ctx = RecommendationContext(total_sessions=10, incomplete_sessions=4, priced=False)
    ids = {r.rule_id for r in recommend(ctx)}
    assert {"interruptions", "unpriced"} <= ids
    # Complete, priced, tested usage stays quiet.
    quiet = RecommendationContext(
        total_sessions=4,
        sessions_with_commands=2,
        sessions_with_tests=2,
        prompt_count=4,
        avg_prompt_length=150,
        priced=True,
    )
    assert recommend(quiet) == []


def test_regen_loop_rule():
    ctx = RecommendationContext(
        total_sessions=2,
        max_edits_one_file_one_session=9,
        max_edits_file="app.py",
        priced=True,
    )
    recs = [r for r in recommend(ctx) if r.rule_id == "regen-loop"]
    assert len(recs) == 1
    assert recs[0].severity == "warning"


def test_recommendations_endpoint(temp_home):
    now = utcnow()

    def evt(sid, event, minutes, **kwargs):
        return UniversalEvent(
            session_id=sid,
            timestamp=now - timedelta(minutes=minutes),
            agent="claude",
            event=event,
            **kwargs,
        )

    events = [evt("s1", EventType.SESSION_STARTED, 120)]
    for i in range(4):
        events.append(
            evt("s1", EventType.PROMPT_SUBMITTED, 110 - i, metadata={"length": 15})
        )
    events.append(
        evt("s1", EventType.TERMINAL_COMMAND, 90, metadata={"command": "ls", "exit_code": 0})
    )
    events.append(evt("s1", EventType.SESSION_ENDED, 60))
    persist_events(events)

    with TestClient(create_app()) as client:
        body = client.get("/recommendations").json()
        ids = {r["rule_id"] for r in body["recommendations"]}
        # Short prompts + commands-without-tests + unpriced (no pricing.json).
        assert {"short-prompts", "untested-sessions", "unpriced"} <= ids
        for rec in body["recommendations"]:
            assert rec["severity"] in ("warning", "suggestion", "info")
            assert rec["message"]
