import {
  AlertTriangle,
  ArrowUpRight,
  CalendarDays,
  Clock,
  Command,
  DollarSign,
  FileEdit,
  FlaskConical,
  Search,
  Terminal,
  Timer,
  Zap,
} from "lucide-react";
import Link from "next/link";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { ActivityChart } from "@/components/observatory/activity-chart";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  exportHref,
  fetchCharts,
  fetchCommandStats,
  fetchFiles,
  fetchPromptStats,
  fetchSessions,
  fetchStats,
} from "@/lib/api";
import { formatCost, formatDuration, formatNumber } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  let stats;
  try {
    stats = await fetchStats();
  } catch (error) {
    return <ApiErrorNotice message={(error as Error).message} />;
  }

  // Everything else is optional: a failure here degrades one section, never
  // the whole page (PRD section 25).
  const [sessionsRes, filesRes, chartsRes, promptsRes, commandsRes] =
    await Promise.allSettled([
      fetchSessions(),
      fetchFiles(),
      fetchCharts("7d"),
      fetchPromptStats(),
      fetchCommandStats(),
    ]);
  const sessions = sessionsRes.status === "fulfilled" ? sessionsRes.value : null;
  const files = filesRes.status === "fulfilled" ? filesRes.value : [];
  const chartPoints = chartsRes.status === "fulfilled" ? chartsRes.value : [];
  const promptStats = promptsRes.status === "fulfilled" ? promptsRes.value : null;
  const commandStats = commandsRes.status === "fulfilled" ? commandsRes.value : null;

  // Agent breakdown from sessions (client-side aggregation for display)
  const byAgent: Record<string, number> = {};
  for (const s of sessions ?? []) byAgent[s.agent] = (byAgent[s.agent] || 0) + 1;

  const cards = [
    { label: "Coding time", value: formatDuration(stats.coding_time_seconds), icon: Timer, hint: "today", accent: "bg-primary/10 text-primary" },
    { label: "Sessions", value: formatNumber(stats.session_count), icon: Clock, hint: `${Object.keys(byAgent).length || 1} agent(s)`, accent: "bg-orange-500/10 text-orange-400" },
    { label: "Files changed", value: formatNumber(stats.files_changed_count), icon: FileEdit, hint: "edits observed", accent: "bg-violet-500/10 text-violet-400" },
    {
      label: "Estimated cost",
      value: formatCost(stats.estimated_cost),
      icon: DollarSign,
      hint: stats.cost_is_estimated ? "priced" : "No pricing configured",
      accent: "bg-emerald-500/10 text-emerald-500",
      note: stats.cost_is_estimated ? undefined : "No pricing configured",
    },
    { label: "Commands", value: formatNumber(stats.command_count), icon: Terminal, hint: "terminal", accent: "bg-sky-500/10 text-sky-400" },
    { label: "Tests", value: formatNumber(stats.test_count), icon: FlaskConical, hint: "runs recorded", accent: "bg-pink-500/10 text-pink-400" },
  ];

  return (
    <div className="space-y-8">
      {/* Header with working search */}
      <div className="flex flex-col gap-4 border-b pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight">Today</h1>
          <p className="flex items-center gap-2 font-mono text-sm text-muted-foreground">
            <CalendarDays className="size-4" />
            {stats.date}
            <span className="mx-2 size-1 rounded-full bg-muted-foreground/30" />
            <span className="inline-flex items-center gap-1">
              <span className="size-1.5 rounded-full bg-success" />
              Local-only • {stats.session_count} session{stats.session_count === 1 ? "" : "s"}
            </span>
          </p>
        </div>
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
          <form action="/search" method="get" className="relative w-full sm:w-64" role="search">
            <label htmlFor="home-search" className="sr-only">
              Search sessions, files and commands
            </label>
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="home-search"
              name="q"
              placeholder="Search sessions, files…"
              className="h-9 bg-muted pl-9 font-mono text-xs"
            />
            <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 items-center gap-1 rounded bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground sm:flex">
              <Command className="size-3" />K
            </kbd>
          </form>
          <Link
            href="/sessions"
            className="inline-flex items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            Explore sessions <ArrowUpRight className="size-3.5" />
          </Link>
        </div>
      </div>

      {sessions === null && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3" role="alert">
          <p className="font-mono text-xs text-muted-foreground">
            Session list failed to load — stats above are still current.
          </p>
        </div>
      )}

      {/* Agent compatibility strip — showcases opencode/kilocode support */}
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          { agent: "claude", title: "Claude Code", desc: "Hooks + transcripts", color: "border-orange-500/20 bg-orange-500/5" },
          { agent: "opencode", title: "OpenCode", desc: "SSE hooks + JSONL", color: "border-primary/20 bg-primary/5" },
          { agent: "kilocode", title: "Kilo Code", desc: "VS Code extension", color: "border-violet-500/20 bg-violet-500/5" },
        ].map((a) => (
          <div key={a.agent} className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${a.color}`}>
            <div className="grid size-9 place-items-center rounded-lg bg-background">
              <Zap className="size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{a.title}</p>
              <p className="font-mono text-xs text-muted-foreground">{a.desc}</p>
            </div>
            <span className="font-mono text-xs tabular-nums text-muted-foreground">{byAgent[a.agent] ?? 0}</span>
          </div>
        ))}
      </div>

      {/* Stats grid — gridline + shadcn card blend */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card, index) => (
          <Card
            key={card.label}
            className="group relative overflow-hidden border bg-card shadow-sm transition-all hover:border-primary/20 hover:shadow-md animate-in fade-in-0 slide-in-from-bottom-1 duration-300 fill-mode-both"
            style={{ animationDelay: `${index * 40}ms` }}
          >
            <div className="absolute inset-0 bg-gradient-to-br from-primary/0 via-transparent to-primary/[0.02] opacity-0 transition-opacity group-hover:opacity-100" />
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <span className={`grid size-7 place-items-center rounded-md ${card.accent}`}>
                  <card.icon className="size-3.5" />
                </span>
                {card.label}
              </CardTitle>
              <span className="font-mono text-[10px] text-muted-foreground">{card.hint}</span>
            </CardHeader>
            <CardContent>
              <p className="font-mono text-3xl font-semibold tabular-nums tracking-tight">{card.value}</p>
              {card.note ? <p className="mt-1 text-xs text-muted-foreground">{card.note}</p> : null}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Activity chart + top files */}
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-base">Activity</CardTitle>
              <CardDescription className="font-mono text-xs">Sessions per day, last 7 days</CardDescription>
            </div>
            <Link href="/sessions" className="inline-flex items-center gap-1 font-mono text-xs text-primary hover:underline">
              All sessions <ArrowUpRight className="size-3" />
            </Link>
          </CardHeader>
          <CardContent>
            {chartPoints.length > 0 ? (
              <ActivityChart points={chartPoints} />
            ) : (
              <p className="font-mono text-xs text-muted-foreground">No chart data yet.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top files</CardTitle>
            <CardDescription className="font-mono text-xs">Most-modified across sessions</CardDescription>
          </CardHeader>
          <CardContent>
            {files.length === 0 ? (
              <p className="font-mono text-xs text-muted-foreground">No file activity yet.</p>
            ) : (
              <ol className="space-y-2">
                {files.slice(0, 5).map((f) => (
                  <li key={f.filename} className="flex items-baseline justify-between gap-2">
                    <span className="truncate font-mono text-xs" title={f.filename}>
                      {f.filename}
                    </span>
                    <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
                      {formatNumber(f.total_modifications)} edits
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Prompt + terminal analytics */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Prompts</CardTitle>
            <CardDescription className="font-mono text-xs">Length-only analytics — text is never stored</CardDescription>
          </CardHeader>
          <CardContent>
            {promptStats && promptStats.count > 0 ? (
              <dl className="grid grid-cols-2 gap-3 font-mono text-xs">
                <div><dt className="text-muted-foreground">Count</dt><dd className="text-lg font-semibold tabular-nums">{formatNumber(promptStats.count)}</dd></div>
                <div><dt className="text-muted-foreground">Avg length</dt><dd className="text-lg font-semibold tabular-nums">{formatNumber(Math.round(promptStats.avg_length))} ch</dd></div>
                <div><dt className="text-muted-foreground">Long (200+ ch)</dt><dd className="tabular-nums">{formatNumber(promptStats.long_count)}</dd></div>
                <div><dt className="text-muted-foreground">Short (&lt;50 ch)</dt><dd className="tabular-nums">{formatNumber(promptStats.short_count)}</dd></div>
              </dl>
            ) : (
              <p className="font-mono text-xs text-muted-foreground">No prompts recorded yet.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Terminal</CardTitle>
            <CardDescription className="font-mono text-xs">Secrets redacted before storage</CardDescription>
          </CardHeader>
          <CardContent>
            {commandStats && commandStats.total > 0 ? (
              <div className="space-y-3 font-mono text-xs">
                <p className="tabular-nums">
                  {formatNumber(commandStats.total)} commands •{" "}
                  {formatNumber(commandStats.failed)} failed (
                  {(commandStats.fail_rate * 100).toFixed(1)}%) • {formatNumber(commandStats.git_count)} git
                </p>
                <ol className="space-y-1.5">
                  {commandStats.top.slice(0, 4).map((t) => (
                    <li key={t.command} className="flex items-baseline justify-between gap-2">
                      <span className="truncate" title={t.command}>{t.command}</span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">×{t.count}</span>
                    </li>
                  ))}
                </ol>
              </div>
            ) : (
              <p className="font-mono text-xs text-muted-foreground">No commands recorded yet.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Export */}
      <Card className="bg-secondary/40 shadow-none">
        <CardContent className="flex flex-col gap-3 pt-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="text-base">Export</CardTitle>
            <CardDescription className="font-mono text-xs">Download local tables as JSON or CSV. Nothing leaves this machine.</CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            {(
              [
                ["sessions", "json"],
                ["sessions", "csv"],
                ["events", "csv"],
              ] as const
            ).map(([table, format]) => (
              <a
                key={`${table}-${format}`}
                href={exportHref(table, format)}
                download
                className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-2 font-mono text-xs hover:bg-muted"
              >
                {table}.{format} <ArrowUpRight className="size-3" />
              </a>
            ))}
          </div>
        </CardContent>
      </Card>

      <WatcherHealth watchers={stats.watchers} />
    </div>
  );
}

function WatcherHealth({ watchers }: { watchers: Record<string, import("@/lib/api").WatcherStatus> }) {
  const entries = Object.entries(watchers);
  if (entries.length === 0) return null;
  const degraded = entries.filter(([, w]) => w.status !== "running");
  if (degraded.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-4 py-3">
        <span className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <span className="size-1.5 rounded-full bg-success animate-pulse" />
          Watchers
        </span>
        {entries.map(([name]) => (
          <span key={name} className="rounded-md bg-success/10 px-2 py-1 font-mono text-xs text-success">
            {name.replace("_", " ")} • running
          </span>
        ))}
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4" role="alert">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <AlertTriangle className="size-4 text-destructive" />
        Telemetry degraded
      </h2>
      <ul className="mt-2 space-y-1">
        {degraded.map(([name, watcher]) => (
          <li key={name} className="font-mono text-xs text-muted-foreground">
            {name}: {watcher.status}
            {watcher.last_error ? ` — ${watcher.last_error}` : null}
          </li>
        ))}
      </ul>
      <p className="mt-2 font-mono text-xs text-muted-foreground">Dashboard stays up — only collection is affected.</p>
    </div>
  );
}
