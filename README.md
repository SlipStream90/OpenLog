# AI Observatory

**The observability layer for AI coding agents.** 100% local-first.

AI Observatory quietly records what your AI coding agent actually did — files
opened and modified, commands run, tests, commits, tokens — and turns it into a
browsable history. It does not replace your agent; it watches it.

No cloud. No accounts. No telemetry. Works with the network disabled.

## Status

Alpha — local telemetry engine, Claude Code adapter, FastAPI backend, and a
Next.js dashboard (dark-mode-first, shadcn/ui).

**Already built:** session capture, timeline replay, file analytics, terminal
analytics, prompt analytics, charts data, search, JSON/CSV export, watcher
infrastructure, REST API.

**Not yet built** (remaining): productivity scoring, recommendations,
Codex CLI adapter.

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Backend

```bash
cd ai-observatory
uv sync --extra dev                          # install Python deps
uv run python scripts/install_claude_hooks.py # register Claude Code hooks
uv run uvicorn backend.api.main:app --port 3141
```

### Dashboard

```bash
cd dashboard
npm install
npm run dev                                  # http://localhost:3000
```

Full instructions, including cost configuration and a verification checklist,
are in [`docs/setup.md`](docs/setup.md).

## How it works

```
Claude Code
   │                         │
   │ hooks (real-time)       │ transcripts (tokens, model)
   ▼                         ▼
hook_handler.py       ~/.claude/projects/**/*.jsonl
   │ appends 1 line
   ▼
~/.ai-observatory/logs/claude_hooks.jsonl
   │                         │
   └────────► ClaudeAdapter ◄┘        all Claude-specific parsing stops here
                   │
                   ▼ UniversalEvent    the only type that crosses this boundary
           single writer coroutine
                   ▼
        SQLite (WAL) ──► FastAPI :3141 ──► Next.js dashboard :3000
```

The hook handler is stdlib-only, does one append, and always exits 0 — it can
never block or interrupt a coding session. Everything heavier happens in the
background watchers inside the API process.

## Layout

```
ai-observatory/
├── backend/
│   ├── shared/          Universal Event model, Adapter protocol, paths
│   ├── adapters/claude/ hook handler, transcript reader, event mapper, adapter
│   ├── telemetry/       watchers, offset persistence, ingestion pipeline
│   ├── database/        SQLAlchemy models, engine, init_db()
│   └── api/             FastAPI app and read-only endpoints
├── dashboard/           Next.js App Router UI (dark-mode-first)
├── scripts/             install_claude_hooks.py
├── tests/               adapter, database and API tests
└── docs/                setup guide and architecture docs
```

## API

`http://localhost:3141` — all read-only, localhost-only.

| Endpoint             | Returns                                  |
| -------------------- | ---------------------------------------- |
| `GET /sessions`      | Every session, newest first (`?agent=`, `?date=`) |
| `GET /session/{id}`  | One session plus aggregate counts        |
| `GET /timeline/{id}` | Ordered event replay                     |
| `GET /files`         | Per-file totals across sessions          |
| `GET /stats`         | Today's aggregates + watcher health      |
| `GET /search?q=`     | Substring search over files/commands/sessions |
| `GET /charts?range=` | Per-day sessions/duration/tokens/cost (`7d`, `30d`) |
| `GET /analytics/prompts` | Prompt count/avg/long-short split    |
| `GET /analytics/commands` | Command totals/fail-rate/top        |
| `GET /export?table=&format=` | Table download as JSON or CSV  |

## Privacy

Prompt **text** is never stored — only its length. Terminal commands are stored
with secrets redacted (`export KEY=…`, `--token …`, `Authorization:` headers,
embedded credentials); source code, prompt text and environment variables never
leave your machine. Raw hook payloads are queue files only and are compacted
once ingested. Nothing in `backend/` imports an HTTP client capable of an
outbound call. There is a test that fails the build if any non-loopback
connection is attempted.

## Tech stack

| Layer    | Stack                                           |
| -------- | ----------------------------------------------- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS, shadcn/ui, Recharts |
| Backend  | FastAPI, SQLAlchemy 2.0, SQLite (WAL mode)      |
| Runtime  | Python 3.11+, uv                                |
| Testing  | pytest                                          |

## Development

```bash
# Run the full test suite
uv run pytest

# Lint the dashboard
cd dashboard && npm run lint

# Quality gates (stdlib-only, no new dependencies)
uv run python scripts/check_duplicates.py --min-lines 25
uv run python scripts/check_coupling.py

# Write today's Markdown summary (needs the backend running)
uv run python scripts/daily_summary.py
```

## Caveats

The Claude Code hook payload schema, transcript schema and `settings.json` hook
format were **not verifiable** when this was built. The adapter probes multiple
plausible field names and degrades gracefully rather than crashing, but confirm
against current documentation before trusting the numbers. See "Known gaps" in
[`docs/setup.md`](docs/setup.md).

## License

MIT.
