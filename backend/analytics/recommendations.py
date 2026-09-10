"""Rule-based recommendations (PRD section 16).

Alpha uses deterministic rules over stored aggregates -- each recommendation
links back to the metric that triggered it (`metric`), so the UI can show
"why" without inventing explanations. Severities: `warning` (likely waste),
`suggestion` (worth trying), `info` (setup nudge).

Thresholds are documented v0 heuristics, tuned once real usage data exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession

from backend.database.models import Command, Event, FileRecord, Prompt, Session
from backend.shared.events import TEST_EVENT_TYPES
from backend.shared.pricing import is_priced

#: Look-back window for "recent" behavior.
WINDOW_DAYS = 7
MAX_RECOMMENDATIONS = 8


@dataclass(frozen=True)
class Recommendation:
    rule_id: str
    severity: str  # warning | suggestion | info
    message: str
    metric: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecommendationContext:
    total_sessions: int = 0
    incomplete_sessions: int = 0
    sessions_with_commands: int = 0
    sessions_with_tests: int = 0
    prompt_count: int = 0
    avg_prompt_length: float = 0.0
    file_session_counts: tuple[tuple[str, int], ...] = ()
    max_edits_one_file_one_session: int = 0
    max_edits_file: str = ""
    priced: bool = False


def build_context(db: SASession, days: int = WINDOW_DAYS) -> RecommendationContext:
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    sessions = (
        db.execute(select(Session).where(Session.start_time >= cutoff)).scalars().all()
    )
    if not sessions:
        return RecommendationContext(priced=is_priced())
    ids = [row.id for row in sessions]

    incomplete = sum(1 for row in sessions if row.end_time is None)

    with_commands = {
        sid
        for (sid,) in db.execute(
            select(Command.session_id).where(Command.session_id.in_(ids)).group_by(
                Command.session_id
            )
        ).all()
    }
    with_tests = {
        sid
        for (sid,) in db.execute(
            select(Event.session_id)
            .where(
                Event.session_id.in_(ids),
                Event.event_type.in_([t.value for t in TEST_EVENT_TYPES]),
            )
            .group_by(Event.session_id)
        ).all()
    }

    prompt_rows = db.execute(
        select(func.count(), func.avg(Prompt.prompt_length)).where(
            Prompt.session_id.in_(ids)
        )
    ).one()
    prompt_count = int(prompt_rows[0] or 0)
    prompt_avg = float(prompt_rows[1] or 0.0)

    file_counts = db.execute(
        select(FileRecord.filename, func.count(func.distinct(FileRecord.session_id)))
        .where(FileRecord.session_id.in_(ids))
        .group_by(FileRecord.filename)
        .order_by(func.count(func.distinct(FileRecord.session_id)).desc())
    ).all()

    burst = db.execute(
        select(Event.session_id, Event.file, func.count())
        .where(Event.session_id.in_(ids), Event.event_type == "file_modified")
        .group_by(Event.session_id, Event.file)
        .order_by(func.count().desc())
        .limit(1)
    ).first()

    return RecommendationContext(
        total_sessions=len(sessions),
        incomplete_sessions=incomplete,
        sessions_with_commands=len(with_commands),
        sessions_with_tests=len(with_tests),
        prompt_count=prompt_count,
        avg_prompt_length=round(prompt_avg, 1),
        file_session_counts=tuple((name, int(n)) for name, n in file_counts[:5]),
        max_edits_one_file_one_session=int(burst[2]) if burst else 0,
        max_edits_file=str(burst[1] or "") if burst else "",
        priced=is_priced(),
    )


def recommend(ctx: RecommendationContext) -> list[Recommendation]:
    """Apply the rule set to a context. Pure: no DB, no I/O."""
    out: list[Recommendation] = []
    if ctx.total_sessions == 0:
        return out

    for filename, n_sessions in ctx.file_session_counts:
        if n_sessions >= 3:
            out.append(
                Recommendation(
                    rule_id="hot-file",
                    severity="warning" if n_sessions >= 5 else "suggestion",
                    message=(
                        f"`{filename}` was modified in {n_sessions} recent sessions. "
                        "Files revisited this often are usually missing an abstraction "
                        "or a test."
                    ),
                    metric={"filename": filename, "sessions": n_sessions},
                )
            )
            break  # one hot-file nudge is enough per digest

    if ctx.max_edits_one_file_one_session >= 8:
        out.append(
            Recommendation(
                rule_id="regen-loop",
                severity="warning",
                message=(
                    f"`{ctx.max_edits_file}` was rewritten "
                    f"{ctx.max_edits_one_file_one_session} times in a single session. "
                    "That usually means regenerating instead of iterating."
                ),
                metric={
                    "filename": ctx.max_edits_file,
                    "edits": ctx.max_edits_one_file_one_session,
                },
            )
        )

    if ctx.prompt_count >= 3 and ctx.avg_prompt_length < 60:
        out.append(
            Recommendation(
                rule_id="short-prompts",
                severity="suggestion",
                message=(
                    f"Average prompt length is only {ctx.avg_prompt_length:.0f} chars "
                    f"across {ctx.prompt_count} prompts. Longer, goal-stating prompts "
                    "tend to need fewer round-trips."
                ),
                metric={
                    "avg_length": ctx.avg_prompt_length,
                    "prompts": ctx.prompt_count,
                },
            )
        )

    if ctx.sessions_with_commands > 0:
        tested_ratio = ctx.sessions_with_tests / ctx.sessions_with_commands
        if tested_ratio < 0.5:
            untested = ctx.sessions_with_commands - ctx.sessions_with_tests
            out.append(
                Recommendation(
                    rule_id="untested-sessions",
                    severity="suggestion",
                    message=(
                        f"{untested} of {ctx.sessions_with_commands} command-running "
                        "sessions recorded no tests. Sessions with automated tests "
                        "score higher and break less often."
                    ),
                    metric={
                        "untested": untested,
                        "with_commands": ctx.sessions_with_commands,
                    },
                )
            )

    if ctx.total_sessions >= 3 and ctx.incomplete_sessions / ctx.total_sessions >= 0.3:
        out.append(
            Recommendation(
                rule_id="interruptions",
                severity="suggestion",
                message=(
                    f"{ctx.incomplete_sessions} of {ctx.total_sessions} recent sessions "
                    "never completed. Frequently interrupting the agent before it "
                    "finishes usually costs more than it saves."
                ),
                metric={
                    "incomplete": ctx.incomplete_sessions,
                    "total": ctx.total_sessions,
                },
            )
        )

    if not ctx.priced:
        out.append(
            Recommendation(
                rule_id="unpriced",
                severity="info",
                message=(
                    "No pricing configured, so costs read $0.00. Add "
                    "`~/.ai-observatory/pricing.json` to track spend."
                ),
                metric={},
            )
        )

    order = {"warning": 0, "suggestion": 1, "info": 2}
    out.sort(key=lambda r: order.get(r.severity, 3))
    return out[:MAX_RECOMMENDATIONS]
