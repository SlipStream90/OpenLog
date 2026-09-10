"""Prompt + terminal analytics from length-only records (PRD §14).

Read-only single-table aggregations over `prompts` and `commands`:

* `GET /analytics/prompts` -- count, average/max length, long/short split,
  per-day frequency. Prompt *text* is never stored, so every metric here is a
  function of lengths and timestamps only.
* `GET /analytics/commands` -- totals, fail rate, git/build split, top
  commands. Command text is the redacted form (see `backend.shared.sanitize`).

Long/short cutoffs and the build-command heuristic are documented v0
heuristics, not ground truth.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as SASession

from backend.api.schemas import (
    CommandStatsResponse,
    PromptDayStat,
    PromptStatsResponse,
    TopCommand,
)
from backend.database.models import Command, Prompt
from backend.database.session import as_utc, get_db

router = APIRouter(tags=["analytics"])

#: v0 cutoffs (chars). "Long" prompts carry real context; "short" ones are
#: usually nudges ("continue", "fix it"). Tune once real data exists.
LONG_PROMPT_CHARS = 200
SHORT_PROMPT_CHARS = 50
TOP_COMMANDS = 10

#: Substring signals for build commands. Documented heuristic: matches the
#: common runners, may miss exotic setups (then they simply land in "other").
_BUILD_SIGNALS = (
    "npm run build",
    "yarn build",
    "pnpm build",
    "cargo build",
    "go build",
    "docker build",
    "tsc ",
    "tsc",
    "webpack",
    "vite build",
    "gradle build",
    "mvn package",
    "mvn install",
)


def _local_date(value: datetime) -> str:
    return as_utc(value).astimezone(datetime.now().astimezone().tzinfo).date().isoformat()


@router.get("/analytics/prompts", response_model=PromptStatsResponse)
def prompt_stats(db: SASession = Depends(get_db)) -> PromptStatsResponse:  # noqa: B008
    rows = db.execute(select(Prompt.prompt_length, Prompt.timestamp)).all()
    if not rows:
        return PromptStatsResponse()

    lengths = [int(length or 0) for length, _ in rows]
    per_day: dict[str, list[int]] = {}
    for length, timestamp in rows:
        per_day.setdefault(_local_date(timestamp), []).append(int(length or 0))

    return PromptStatsResponse(
        count=len(lengths),
        avg_length=round(sum(lengths) / len(lengths), 2),
        max_length=max(lengths),
        long_count=sum(1 for n in lengths if n >= LONG_PROMPT_CHARS),
        short_count=sum(1 for n in lengths if n < SHORT_PROMPT_CHARS),
        per_day=[
            PromptDayStat(
                date=label,
                count=len(ns),
                avg_length=round(sum(ns) / len(ns), 2),
            )
            for label, ns in sorted(per_day.items())
        ],
    )


@router.get("/analytics/commands", response_model=CommandStatsResponse)
def command_stats(db: SASession = Depends(get_db)) -> CommandStatsResponse:  # noqa: B008
    rows = db.execute(select(Command.command, Command.exit_code)).all()
    if not rows:
        return CommandStatsResponse()

    total = len(rows)
    failed = sum(1 for _, code in rows if code is not None and code != 0)
    counts: Counter[str] = Counter()
    fails: Counter[str] = Counter()
    git_count = 0
    build_count = 0
    for command, code in rows:
        text = command or ""
        counts[text] += 1
        if code is not None and code != 0:
            fails[text] += 1
        lowered = text.strip().lower()
        if lowered.startswith("git "):
            git_count += 1
        if any(signal in lowered for signal in _BUILD_SIGNALS):
            build_count += 1

    top = [
        TopCommand(command=text, count=counts[text], fail_count=fails.get(text, 0))
        for text, _ in counts.most_common(TOP_COMMANDS)
    ]
    return CommandStatsResponse(
        total=total,
        succeeded=sum(1 for _, code in rows if code == 0),
        failed=failed,
        fail_rate=round(failed / total, 4),
        git_count=git_count,
        build_count=build_count,
        top=top,
    )
