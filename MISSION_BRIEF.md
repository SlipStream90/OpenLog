# Mission Brief: AI Observatory — Milestone 1 + 2

This mission builds against the full PRD at `prd.md` in this same directory (read it in full for
product context, universal event schema, database schema, API surface, UI spec, tech stack, and
guiding principles — sections referenced below by number all refer to that file).

Scope for THIS mission is deliberately narrower than the full PRD: implement Milestone 1
(local telemetry engine + Claude Code adapter) and Milestone 2 (FastAPI backend + dashboard
shell) only. Do not implement Milestone 3 (analytics/productivity engine/recommendations) or
Milestone 4 (charts/export/polish) yet. Codex CLI adapter is out of scope for this mission —
leave an empty `backend/adapters/codex/` placeholder only.

## Goal

A working end-to-end local pipeline: Claude Code activity -> normalized Universal Events ->
SQLite -> FastAPI -> a browsable Next.js dashboard (session list + session timeline replay +
today's summary). No charts, no analytics/productivity scoring, no recommendations in this pass.

## Architecture Decisions (authoritative for this mission)

**Event capture (Claude Code adapter) — hooks + transcripts, reconciled by session_id:**
- Hooks (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`/`SessionEnd`)
  give real-time events (file edits, commands run, prompts submitted) via Claude Code's hook
  system, configured in `.claude/settings.json`.
- Hooks must be fast and must never block or interrupt the coding session (PRD principles:
  "Passive", "never interrupt a coding session" — see PRD section 25). The hook handler must be
  a minimal stdlib-only Python script that reads hook JSON from stdin and appends one JSON line
  to a local queue file (`~/.ai-observatory/logs/claude_hooks.jsonl`), then exits immediately —
  no DB writes, no network calls, no heavy imports on the hook's hot path.
- Transcripts (`~/.claude/projects/**/*.jsonl`) are polled separately by a background watcher to
  backfill data hooks don't expose well: token counts, model name, message content (for future
  prompt-length analytics), cost estimation.
- A background Telemetry Engine (asyncio tasks running inside the FastAPI process lifespan —
  single process, no separate daemon) tails both sources, normalizes into the Universal Event
  Model (PRD section 12), and writes to SQLite via SQLAlchemy. Errors in one watcher must be
  caught/logged and must never crash the app or the dashboard (PRD section 25).

**Storage:** SQLite at `~/.ai-observatory/database.sqlite`. Schema per PRD section 13: Sessions,
Events, Files, Commands, Prompts. Skip the `Statistics` table for now — it's analytics-engine
output (Milestone 3). On first run, create `~/.ai-observatory/{sessions,analytics,logs,cache}/`
and the DB tables.

**Backend API (subset of PRD section 17, on `http://localhost:3141`):**
`GET /sessions`, `GET /session/{id}`, `GET /timeline/{id}`, `GET /files`, and a basic
`GET /stats` (raw aggregates only — no productivity score). Do NOT implement `/charts`,
`/recommendations`, or `/search` in this mission.

**Dashboard (Next.js, App Router, TypeScript, Tailwind, shadcn/ui, dark-mode-first per PRD
section 20):** exactly three views for this mission:
1. Home — today's summary cards (coding time, sessions, files changed, cost, commands, tests).
   No charts yet.
2. Sessions — table per PRD section 14 columns (Date, Agent, Duration, Files, Commands, Tokens,
   Cost, Productivity — Productivity column can show a placeholder/N/A since scoring is M3),
   linking to session detail.
3. Session detail — timeline replay view per the PRD section 14 example sequence, backed by
   `GET /timeline/{id}`.

## Folder Structure (per PRD section 10, use this exact layout)

```
ai-observatory/
  dashboard/                 # Next.js app
  backend/
    api/                     # FastAPI routers
    telemetry/               # hook/transcript watchers, normalizer, ingestion
    database/                # SQLAlchemy models, session/engine setup
    analytics/                # placeholder package for later milestones, empty for now
    adapters/
      claude/                 # hook handler script + transcript parser
      codex/                   # empty placeholder, not implemented this mission
      future/
    shared/                   # Universal Event model, shared types/enums
  docs/
  tests/
  scripts/                    # dev helper scripts (e.g. install hooks)
```

Root: `pyproject.toml` (uv-managed package management per PRD section 19), `README.md`.

## Implementation Steps

1. Scaffold repo: `pyproject.toml` (uv), backend package layout above, `dashboard/` via
   create-next-app (TypeScript, Tailwind, App Router), shadcn/ui init, pytest config.
2. Shared Universal Event model (`backend/shared/events.py`): model matching PRD section 12
   schema (`session_id`, `timestamp`, `agent`, `model`, `event`, `file`, `metadata`), plus the
   enum of supported event types listed in that section.
3. Database layer (`backend/database/`): SQLAlchemy models for Sessions, Events, Files,
   Commands, Prompts (PRD section 13); engine pointed at `~/.ai-observatory/database.sqlite`;
   an `init_db()` that creates the local storage directories and tables on first run.
4. Claude Code adapter (`backend/adapters/claude/`):
   - `hook_handler.py`: stdlib-only entrypoint invoked by Claude Code hooks; reads hook JSON
     from stdin, appends a line to `~/.ai-observatory/logs/claude_hooks.jsonl`.
   - `transcript_reader.py`: locates and tails `~/.claude/projects/**/*.jsonl`, extracts token
     usage/model/cost/message text per session.
   - Implements the `Adapter` interface from PRD section 18 (`initialize`, `start_session`,
     `capture_event`, `end_session`), normalizing raw hook/transcript data into Universal Events.
     The analytics engine must never need agent-specific logic — all agent-specific parsing
     stays inside this adapter.
   - `scripts/install_claude_hooks.py`: helper that registers the hooks in `~/.claude/settings.json`
     (or project-level settings), so installation is a real, repeatable, scripted step.
5. Telemetry engine (`backend/telemetry/`): background asyncio tasks (queue-file tailer +
   transcript poller) started in FastAPI's lifespan, feeding normalized events through the
   adapter into the DB layer. Catch and log errors per-watcher so one failing watcher disables
   only itself, never the whole app (PRD section 25).
6. FastAPI backend (`backend/api/`): app on `http://localhost:3141`, the endpoint subset listed
   above, SQLAlchemy session dependency, CORS enabled for the Next.js dev server.
7. Dashboard (`dashboard/`): dark theme base layout; the three pages described above, each
   fetching real data from the local API. No charts (Recharts wiring is a later milestone).
8. Tests (pytest): adapter normalization (hook JSON -> Universal Event), DB layer (insert/query
   round-trip), and API endpoints (FastAPI TestClient against a temp SQLite DB).
9. Docs: a short `docs/setup.md` covering hook installation and running the backend/dashboard
   locally.

## Constraints carried over from the PRD (do not violate)

- 100% local-first: no cloud calls, no telemetry/analytics/tracking of the tool itself, must
  keep working with the network disabled (PRD sections 5, 21).
- Never send source code, prompts, terminal history, secrets, or env vars anywhere off-machine.
- Never interrupt or crash the user's coding session; degrade gracefully per-adapter on failure.
- Keep adapters isolated from the analytics/API layers — only Universal Events cross that
  boundary.
- Startup should be fast and idle footprint small (PRD section 26 performance targets apply
  even though full analytics aren't built yet — don't add unnecessary background work).

## Verification

- `uv run pytest` — adapter normalization, DB round-trip, and API endpoint tests all pass.
- Run `scripts/install_claude_hooks.py`, then exercise Claude Code in a scratch project;
  confirm `~/.ai-observatory/logs/claude_hooks.jsonl` receives events and
  `~/.ai-observatory/database.sqlite` gets populated.
- Start the backend (`uv run uvicorn backend.api.main:app --port 3141`) and confirm
  `/sessions`, `/session/{id}`, `/timeline/{id}`, `/stats` return sensible shapes.
- Start the dashboard (`npm run dev` in `dashboard/`), confirm Home/Sessions/Session-detail
  render real data from the local API, dark theme looks correct, and the app keeps working with
  network connectivity disabled.
