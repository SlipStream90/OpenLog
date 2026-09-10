"use client";

import { ArrowUpRight, Inbox, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { SessionSummary } from "@/lib/api";
import { formatCost, formatDuration, formatNumber, formatTimestamp } from "@/lib/utils";

const agentBadge: Record<string, string> = {
  claude: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  opencode: "bg-primary/10 text-primary border-primary/20",
  kilocode: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  codex: "bg-sky-500/10 text-sky-400 border-sky-500/20",
};

export function SessionsTable({
  sessions,
  initialAgent = "all",
  initialDate = "",
}: {
  sessions: SessionSummary[];
  initialAgent?: string;
  initialDate?: string;
}) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) =>
      [s.id, s.agent, s.model ?? "", formatTimestamp(s.start_time)]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [sessions, query]);

  const pills = ["all", "claude", "opencode", "kilocode", "codex"];
  const dateParam = initialDate ? `&date=${encodeURIComponent(initialDate)}` : "";

  if (sessions.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-10 text-center">
        <Inbox className="mx-auto size-6 text-muted-foreground" />
        <p className="mt-3 text-sm font-medium">Nothing recorded yet</p>
        <p className="mt-2 font-mono text-xs text-muted-foreground">Install hooks for Claude, OpenCode or Kilo Code — sessions appear here automatically.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <label htmlFor="sessions-filter" className="sr-only">
            Filter sessions by text
          </label>
          <Input
            id="sessions-filter"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions, models…"
            className="pl-9 font-mono text-xs bg-muted border-0"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {pills.map((a) => {
            const active = initialAgent === a;
            const href =
              a === "all" ? `/sessions${initialDate ? `?date=${encodeURIComponent(initialDate)}` : ""}` : `/sessions?agent=${a}${dateParam}`;
            return (
              <Link
                key={a}
                href={href}
                aria-pressed={active}
                className={`rounded-full border px-3 py-1 font-mono text-xs capitalize ${active ? "bg-primary text-primary-foreground border-primary" : "bg-muted text-muted-foreground border-transparent hover:bg-muted/80"}`}
              >
                {a}
              </Link>
            );
          })}
          <form action="/sessions" method="get" className="flex items-center gap-1.5">
            {initialAgent !== "all" && <input type="hidden" name="agent" value={initialAgent} />}
            <label htmlFor="sessions-date" className="sr-only">
              Filter sessions by date
            </label>
            <Input
              id="sessions-date"
              type="date"
              name="date"
              defaultValue={initialDate}
              className="h-7 w-auto bg-muted border-0 font-mono text-xs"
            />
            <button
              type="submit"
              className="rounded-full border border-transparent bg-muted px-3 py-1 font-mono text-xs text-muted-foreground hover:bg-muted/80"
            >
              Go
            </button>
            {initialDate && (
              <Link
                href={initialAgent === "all" ? "/sessions" : `/sessions?agent=${initialAgent}`}
                className="rounded-full border border-transparent px-2 py-1 font-mono text-xs text-muted-foreground hover:underline"
              >
                Clear
              </Link>
            )}
          </form>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Date</TableHead>
              <TableHead>Agent</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead className="text-right">Files</TableHead>
              <TableHead className="text-right">Commands</TableHead>
              <TableHead className="text-right">Tokens</TableHead>
              <TableHead className="text-right">Cost</TableHead>
              <TableHead className="text-right">Productivity</TableHead>
              <TableHead className="text-right">Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((session) => (
              <TableRow key={session.id} className="group">
                <TableCell>
                  <Link href={`/sessions/${encodeURIComponent(session.id)}`} className="font-medium underline-offset-4 group-hover:underline">
                    {formatTimestamp(session.start_time)}
                  </Link>
                  <div className="font-mono text-xs text-muted-foreground">{session.model ?? "unknown model"}</div>
                  <div className="font-mono text-[10px] text-muted-foreground/60 truncate max-w-[180px]">{session.id}</div>
                </TableCell>
                <TableCell>
                  <span className={`inline-flex rounded-md border px-2 py-0.5 font-mono text-xs ${agentBadge[session.agent] ?? "bg-muted text-muted-foreground"}`}>
                    {session.agent}
                  </span>
                </TableCell>
                <TableCell className="tabular-nums font-mono text-xs">{formatDuration(session.duration_seconds)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums text-xs">{formatNumber(session.file_count)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums text-xs">{formatNumber(session.command_count)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums text-xs">{formatNumber(session.token_count)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums text-xs">{formatCost(session.estimated_cost)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums text-xs">
                  {session.productivity === null || session.productivity === undefined ? (
                    <span className="text-muted-foreground">N/A</span>
                  ) : (
                    <span
                      className={
                        session.productivity >= 70
                          ? "text-emerald-500"
                          : session.productivity >= 40
                            ? "text-amber-500"
                            : "text-destructive"
                      }
                    >
                      {Math.round(session.productivity)}
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <Link href={`/sessions/${encodeURIComponent(session.id)}`} className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                    replay <ArrowUpRight className="size-3" />
                  </Link>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {filtered.length === 0 && <p className="p-6 text-center font-mono text-sm text-muted-foreground">No sessions match “{query}”.</p>}
      </div>
      <p className="font-mono text-xs text-muted-foreground">{filtered.length} of {sessions.length} sessions • docs →</p>
      <div className="flex gap-4">
        <a href="https://opencode.ai" target="_blank" rel="noreferrer" className="font-mono text-xs text-muted-foreground hover:underline">
          opencode.ai
        </a>
        <a href="https://github.com/Kilo-Org/kilocode" target="_blank" rel="noreferrer" className="font-mono text-xs text-muted-foreground hover:underline">
          kilocode
        </a>
      </div>
    </div>
  );
}
