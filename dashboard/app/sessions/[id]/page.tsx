import {
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  DollarSign,
  FileEdit,
  Gauge,
  GitCommitHorizontal,
  Hash,
  ListTree,
  Terminal,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiErrorNotice, EmptyState } from "@/components/api-error-notice";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, fetchSession, fetchTimeline, type SessionDetail, type TimelineEvent } from "@/lib/api";
import { formatClock, formatCost, formatDuration, formatNumber, formatTimestamp } from "@/lib/utils";

const EVENT_ICONS: Record<string, LucideIcon> = {
  file_opened: FileEdit,
  file_modified: FileEdit,
  file_deleted: FileEdit,
  terminal_command: Terminal,
  test_passed: CheckCircle2,
  test_failed: XCircle,
  git_commit: GitCommitHorizontal,
  prompt_submitted: ListTree,
  response_received: Hash,
  session_started: Clock3,
  session_ended: Clock3,
};

export const dynamic = "force-dynamic";

const agentBadge: Record<string, string> = {
  claude: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  opencode: "bg-primary/10 text-primary border-primary/20",
  kilocode: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  codex: "bg-sky-500/10 text-sky-400 border-sky-500/20",
};

export default async function SessionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: rawId } = await params;
  const id = decodeURIComponent(rawId);
  let session: SessionDetail;
  let events: TimelineEvent[];
  try {
    [session, events] = await Promise.all([fetchSession(id), fetchTimeline(id)]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return <ApiErrorNotice message={(error as Error).message} />;
  }

  const stats = [
    { label: "Duration", value: formatDuration(session.duration_seconds), icon: Clock3, hint: "wall time" },
    { label: "Tokens", value: formatNumber(session.token_count), icon: Hash, hint: session.model ?? "unknown" },
    { label: "Files", value: formatNumber(session.file_count), icon: FileEdit, hint: "distinct" },
    { label: "Commands", value: formatNumber(session.command_count), icon: Terminal, hint: "executions" },
    { label: "Tests passed", value: formatNumber(session.test_pass_count), icon: CheckCircle2, hint: "∕ " + formatNumber(session.test_fail_count) + " failed" },
    { label: "Tests failed", value: formatNumber(session.test_fail_count), icon: XCircle, hint: "check logs" },
    { label: "Commits", value: formatNumber(session.commit_count), icon: GitCommitHorizontal, hint: "git" },
    { label: "Cost", value: formatCost(session.estimated_cost), icon: DollarSign, hint: "estimated" },
    {
      label: "Productivity",
      value: session.productivity === null || session.productivity === undefined ? "N/A" : String(Math.round(session.productivity)),
      icon: Gauge,
      hint: "0–100",
    },
  ];

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-2 border-b pb-5">
        <Link href="/sessions" className="inline-flex w-fit items-center gap-1 font-mono text-xs text-muted-foreground hover:text-foreground hover:underline">
          ← All sessions
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{formatTimestamp(session.start_time)}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className={`inline-flex rounded-md border px-2 py-1 font-mono text-xs ${agentBadge[session.agent] ?? "bg-muted"}`}>{session.agent}</span>
              <span className="rounded-md bg-muted px-2 py-1 font-mono text-xs">{session.model ?? "unknown model"}</span>
              <span className="font-mono text-xs text-muted-foreground">{session.id}</span>
            </div>
          </div>
          <div className="rounded-xl border bg-card px-4 py-3 text-right">
            <p className="font-mono text-xs text-muted-foreground">Session ID</p>
            <p className="font-mono text-xs break-all">{session.id.slice(0, 24)}…</p>
            <p className="mt-1 flex items-center justify-end gap-1 font-mono text-xs text-primary">
              replayable <ArrowUpRight className="size-3" />
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, index) => (
          <Card
            key={stat.label}
            className="group overflow-hidden border bg-card shadow-sm transition-all hover:border-primary/20 hover:shadow-md animate-in fade-in-0 slide-in-from-bottom-1 duration-300 fill-mode-both"
            style={{ animationDelay: `${index * 30}ms` }}
          >
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                <stat.icon className="size-3.5" />
                {stat.label}
              </CardTitle>
              <span className="font-mono text-[10px] text-muted-foreground">{stat.hint}</span>
            </CardHeader>
            <CardContent>
              <p className="font-mono text-2xl font-semibold tabular-nums tracking-tight">{stat.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <section className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
              <ListTree className="size-5" />
              Timeline
              <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-xs">{events.length}</span>
            </h2>
            <span className="font-mono text-xs text-muted-foreground">observable replay • no reasoning exposed</span>
          </div>
          {events.length === 0 ? (
            <EmptyState icon={ListTree} title="No events recorded for this session" />
          ) : (
            <div className="rounded-xl border bg-card p-6">
              <ol className="relative border-l border-border pl-6">
                {events.map((event, index) => {
                  const EventIcon = EVENT_ICONS[event.event_type];
                  const isImportant = ["test_failed", "test_passed", "git_commit", "file_modified"].includes(event.event_type);
                  return (
                    <li key={`${event.timestamp}-${index}`} className="relative pb-6 last:pb-0">
                      <span className={`absolute -left-[1.9375rem] top-0.5 flex size-4 items-center justify-center rounded-full border bg-card ${isImportant ? "border-primary/30 bg-primary/10" : "border-border"}`}>
                        {EventIcon ? <EventIcon aria-hidden className={`size-2.5 ${isImportant ? "text-primary" : "text-muted-foreground"}`} /> : <span className="size-1.5 rounded-full bg-muted-foreground" />}
                      </span>
                      <div className="flex flex-wrap items-baseline gap-x-3">
                        <time className="font-mono text-xs tabular-nums text-muted-foreground">{formatClock(event.timestamp)}</time>
                        <span className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">{event.event_type}</span>
                        <span className="text-sm font-medium">{event.label}</span>
                      </div>
                      {event.file && <p className="mt-1 font-mono text-xs text-primary">{event.file}</p>}
                      <EventDetail event={event} />
                    </li>
                  );
                })}
              </ol>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <Card className="bg-secondary/30">
            <CardHeader>
              <CardTitle className="text-sm">About this replay</CardTitle>
              <CardDescription className="font-mono text-xs">Labels come verbatim from the API. No interpretation of model intent.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 font-mono text-xs text-muted-foreground">
              <p>Agent: <span className="text-foreground">{session.agent}</span></p>
              <p>Model: <span className="text-foreground">{session.model ?? "—"}</span></p>
              <p>Tokens: <span className="text-foreground">{formatNumber(session.token_count)}</span></p>
              <p>Prompt text is never stored — only length.</p>
              <div className="pt-2">
                <Link href="/sessions" className="font-mono text-xs text-primary hover:underline">Back to sessions</Link>
              </div>
            </CardContent>
          </Card>
          <Card className="border-dashed">
            <CardContent className="pt-6 text-center">
              <p className="font-mono text-xs text-muted-foreground">Need multi-agent filtering?</p>
              <p className="mt-1 text-sm font-medium">All sessions table supports “claude / opencode / kilo” pills.</p>
            </CardContent>
          </Card>
          {session.productivity_reasons && session.productivity_reasons.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Gauge className="size-4" />
                  Why this score
                </CardTitle>
                <CardDescription className="font-mono text-xs">
                  Deterministic factors — every point is explainable.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1.5">
                  {session.productivity_reasons.map((reason) => (
                    <li key={reason} className="font-mono text-xs tabular-nums text-muted-foreground">
                      {reason}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      </section>
    </div>
  );
}

function EventDetail({ event }: { event: TimelineEvent }) {
  const parts: string[] = [];
  const added = event.metadata?.lines_added;
  const removed = event.metadata?.lines_removed;
  if (typeof added === "number" || typeof removed === "number") parts.push(`+${Number(added ?? 0)} / −${Number(removed ?? 0)}`);
  const exitCode = event.metadata?.exit_code;
  if (typeof exitCode === "number") parts.push(`exit ${exitCode}`);
  const length = event.metadata?.length;
  if (typeof length === "number") parts.push(`${length} chars`);
  const tokens = event.metadata?.token_count;
  if (typeof tokens === "number") parts.push(`${tokens.toLocaleString()} tokens`);
  if (parts.length === 0) return null;
  return <p className="mt-1 font-mono text-xs text-muted-foreground">{parts.join(" · ")}</p>;
}
