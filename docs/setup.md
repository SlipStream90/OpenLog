# Setup

AI Observatory runs entirely on your machine: one Python process (API + telemetry)
and one Node process (dashboard). Nothing is sent anywhere.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Node 18+ and npm
- Claude Code (for the adapter to have anything to observe)

## 1. Install the backend

```bash
uv sync --extra dev
```

This creates the virtualenv and installs FastAPI, SQLAlchemy, Pydantic, uvicorn
and the test dependencies.

## 2. Install the Claude Code hooks

```bash
uv run python scripts/install_claude_hooks.py
```

This registers `backend/adapters/claude/hook_handler.py` against the
`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop` and
`SessionEnd` hooks in `~/.claude/settings.json`.

The installer:

- backs up your existing settings to `settings.json.bak` before writing,
- merges into whatever hooks you already have (never overwrites the file),
- is idempotent — re-running it adds nothing,
- asks for confirmation before writing.

Useful flags:

| Flag | Effect |
|---|---|
| `--project` | write to `./.claude/settings.json` instead of the user-level file |
| `--dry-run` | print the resulting settings, write nothing |
| `--uninstall` | remove only our entries |
| `--yes` | skip the confirmation prompt |

**Restart Claude Code** afterwards for the hooks to take effect.

> ⚠️ The exact `settings.json` hook format is **[UNVERIFIED]** in this build —
> it could not be checked against live documentation or a real install (see
> "Known gaps" below). Run `--dry-run` first, and keep the `.bak` file.

## 3. Run the backend

```bash
uv run uvicorn backend.api.main:app --port 3141
```

On first run this creates `~/.ai-observatory/` with `database.sqlite` and the
`sessions/`, `analytics/`, `logs/` and `cache/` directories, then starts the two
background watchers inside the same process.

Check the endpoints:

```bash
curl http://localhost:3141/sessions
curl http://localhost:3141/stats
```

## 4. Run the dashboard

```bash
cd dashboard
npm install
npx next telemetry disable   # optional, keeps Next.js from phoning home
npm run dev
```

Open <http://localhost:3000>. Three pages: **Home** (today's summary), **Sessions**
(all sessions), and **Session detail** (timeline replay).

If the backend is not running, the dashboard renders a clear message rather than
crashing.

## 5. Configure cost estimation (optional)

`estimated_cost` is `0.00` until you supply prices, and the Home page labels it
"No pricing configured" rather than implying the day was free. Prices ship empty
deliberately — see `backend/adapters/claude/pricing.py` for why.

Create `~/.ai-observatory/pricing.json` (USD per million tokens):

```json
{
  "claude-sonnet-4-5": { "input_per_mtok": 3.00, "output_per_mtok": 15.00 },
  "claude-opus-4": { "input_per_mtok": 15.00, "output_per_mtok": 75.00 }
}
```

Model keys match by longest prefix, so `"claude-sonnet"` covers every dated
snapshot. Restart the backend to pick up changes.

## Verification checklist

Per `MISSION_BRIEF.md`:

1. **Tests** — `uv run pytest`. Adapter normalization, DB round-trip and API
   endpoint tests should all pass.
2. **Hook capture** — run the installer, use Claude Code in a scratch project,
   then confirm `~/.ai-observatory/logs/claude_hooks.jsonl` is growing.
3. **Ingestion** — with the backend running, confirm `~/.ai-observatory/database.sqlite`
   gets populated (`GET /sessions` returns rows).
4. **API** — `/sessions`, `/session/{id}`, `/timeline/{id}`, `/files`, `/stats`
   return sensible shapes.
5. **Dashboard** — all three pages render real data, dark theme correct.
6. **Offline** — disable network connectivity; everything above must still work.

## Troubleshooting

**Nothing appears in `claude_hooks.jsonl`.** The hook handler is silent by
design — it never writes stderr and always exits 0, so a coding session is never
interrupted (ADR-007). To test it directly:

```bash
echo '{"session_id":"test","hook_event_name":"SessionStart"}' | uv run python backend/adapters/claude/hook_handler.py
cat ~/.ai-observatory/logs/claude_hooks.jsonl
```

If that writes a line but real sessions do not, the hook registration format is
wrong — see "Known gaps".

**Queue file grows but the database stays empty.** Check `GET /stats` → `watchers`.
A `degraded` watcher reports its error there, and the Home page surfaces it.

**Events land under `unmatched-claude-...`.** The adapter could not find a session
id in the payload, so it bucketed the events by hour rather than dropping them
(ADR-001). This means the real field name differs from what `event_mapper.py`
probes for — add it to `FIELD_ALIASES`.

## Known gaps

Three external facts could **not be verified** while this was built (every
documentation-fetch route and reads of a live `~/.claude/` install were blocked):

1. the hook payload JSON schema,
2. the transcript JSONL schema,
3. the `settings.json` hook registration format.

All three are confined to `backend/adapters/claude/` and
`scripts/install_claude_hooks.py`. The adapter probes several plausible field
names and degrades to `None` with a log line rather than crashing, so a wrong
guess costs you a null field, not a broken app. Confirm against current Claude
Code documentation before trusting the numbers.

Also not implemented, deliberately (Milestone 3/4): productivity scoring,
recommendations, charts, export, search, and the Codex CLI adapter.
