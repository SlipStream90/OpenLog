"""Deterministic productivity scoring (PRD section 15).

Scores are computed from stored aggregates only, with fixed weights, so every
point is explainable: `score_session` returns the score *and* the list of
human-readable reasons that produced it. No ML, no opaque model, no network.

Factor set (PRD §15, mapped to what the schema actually stores):

Positive
    session completion (`session_ended` observed) ............ +10
    git commits (+8 each, cap +24)
    test pass rate (+12 scaled, when tests ran)
    distinct files touched (+2 each, cap +10)

Negative
    failed tests (-4 each, cap -16)
    error events (-4 each, cap -12)
    repeated edits (edits beyond 3x the files touched, -2 each, cap -15)
    abandonment (no `session_ended`: -6, -10 when under 5 minutes)
    prompt churn (>=8 prompts averaging under 40 chars: -8)
    commands with no tests at all (-5)

Base is 50; the result is clamped to 0-100 and rounded to an int. A session
with no evidence at all scores `None`, not 0 -- an honest gap, never a
fabricated number (PRD section 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SessionFactors:
    """Everything the score needs, pre-aggregated by the caller."""

    completed: bool = False
    duration_seconds: float = 0.0
    commits: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    tests_executed: int = 0  # outcome unknown; counts as "ran", not as pass/fail
    prompts: int = 0
    avg_prompt_length: float = 0.0
    distinct_files: int = 0
    edits: int = 0  # file_modified events
    errors: int = 0
    commands: int = 0


@dataclass(frozen=True)
class ScoredProductivity:
    score: int
    reasons: list[str] = field(default_factory=list)


def score_session(factors: SessionFactors) -> ScoredProductivity | None:
    """Score one session. `None` when there is nothing to score."""
    total_signals = (
        factors.commits
        + factors.tests_passed
        + factors.tests_failed
        + factors.tests_executed
        + factors.prompts
        + factors.distinct_files
        + factors.edits
        + factors.errors
        + factors.commands
    )
    if not factors.completed and total_signals == 0:
        return None

    score = 50.0
    reasons: list[str] = []

    def add(points: float, reason: str) -> None:
        nonlocal score
        if not points:
            return
        score += points
        reasons.append(f"{points:+g} {reason}")

    if factors.completed:
        add(10, "session completed")
    else:
        add(-10 if factors.duration_seconds < 300 else -6, "session never completed")

    if factors.commits:
        add(min(factors.commits * 8, 24), f"{factors.commits} commit(s)")

    test_events = factors.tests_passed + factors.tests_failed + factors.tests_executed
    if test_events:
        decided = factors.tests_passed + factors.tests_failed
        rate = (factors.tests_passed / decided) if decided else 0.0
        add(round(rate * 12, 2), f"test pass rate {rate:.0%}")
        add(-min(factors.tests_failed * 4, 16), f"{factors.tests_failed} failed test(s)")
    elif factors.commands:
        add(-5, "commands ran but no tests recorded")

    if factors.distinct_files:
        add(min(factors.distinct_files * 2, 10), f"{factors.distinct_files} file(s) touched")

    if factors.errors:
        add(-min(factors.errors * 4, 12), f"{factors.errors} error(s)")

    excess_edits = factors.edits - 3 * max(factors.distinct_files, 1)
    if excess_edits > 0:
        add(-min(excess_edits * 2, 15), f"{excess_edits} repeated edit(s)")

    if factors.prompts >= 8 and factors.avg_prompt_length < 40:
        add(-8, f"{factors.prompts} short prompts (avg {factors.avg_prompt_length:.0f} chars)")

    return ScoredProductivity(score=int(round(max(0.0, min(100.0, score)))), reasons=reasons)
