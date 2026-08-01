import {
  CheckCircle2,
  Clock3,
  DollarSign,
  FileEdit,
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ApiError,
  fetchSession,
  fetchTimeline,
  type SessionDetail,
  type TimelineEvent,
} from "@/lib/api";
import { formatClock, formatCost, formatDuration, formatNumber, formatTimestamp } from "@/lib/utils";

// Purely decorative -- keyed on the typed `event_type` field, never on the
// free-text `label`. An unrecognized type falls back to a plain dot rather
// than guessing, since new event types are expected to appear over time.
const EVENT_ICONS: Record<string, LucideIcon> = {
  file_opened: FileEdit,
  file_modified: FileEdit,
  file_deleted: FileEdit,
  terminal_command: Terminal,
  test_passed: CheckCircle2,
  test_failed: XCircle,
  git_commit: GitCommitHorizontal,
};

export const dynamic = "force-dynamic";

/**
 * Session detail -- stats header plus the timeline replay (PRD section 14).
 *
 * The timeline is an observable action replay. Labels come from the API
 * verbatim and are rendered as-is; the UI adds no interpretation of what the
 * model was "trying" to do.
 */
export default async function SessionDetailPage({ params }: { params: { id: string } }) {
  const id = decodeURIComponent(params.id);

  let session: SessionDetail;
  let events: TimelineEvent[];
  try {
    [session, events] = await Promise.all([fetchSession(id), fetchTimeline(id)]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    return <ApiErrorNotice message={(error as Error).message} />;
  }

  const stats = [
    { label: "Duration", value: formatDuration(session.duration_seconds), icon: Clock3 },
    { label: "Tokens", value: formatNumber(session.token_count), icon: Hash },
    { label: "Files", value: formatNumber(session.file_count), icon: FileEdit },
    { label: "Commands", value: formatNumber(session.command_count), icon: Terminal },
    { label: "Tests passed", value: formatNumber(session.test_pass_count), icon: CheckCircle2 },
    { label: "Tests failed", value: formatNumber(session.test_fail_count), icon: XCircle },
    { label: "Commits", value: formatNumber(session.commit_count), icon: GitCommitHorizontal },
    { label: "Cost", value: formatCost(session.estimated_cost), icon: DollarSign },
  ];

  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/sessions"
          className="text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          ← All sessions
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          {formatTimestamp(session.start_time)}
        </h1>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {session.agent} · {session.model ?? "unknown model"} · {session.id}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, index) => (
          <Card
            key={stat.label}
            className="animate-in fade-in-0 slide-in-from-bottom-1 duration-300 fill-mode-both"
            style={{ animationDelay: `${index * 30}ms` }}
          >
            <CardHeader className="pb-2">
              <CardTitle>
                <stat.icon className="h-3.5 w-3.5" aria-hidden />
                {stat.label}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="font-mono text-2xl font-semibold tabular-nums tracking-tight">
                {stat.value}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight">Timeline</h2>
        {events.length === 0 ? (
          <EmptyState icon={ListTree} title="No events recorded for this session" />
        ) : (
          <ol className="relative border-l border-border pl-6">
            {events.map((event, index) => {
              const EventIcon = EVENT_ICONS[event.event_type];
              return (
              <li key={`${event.timestamp}-${index}`} className="relative pb-6 last:pb-0">
                <span
                  className="absolute -left-[1.9375rem] top-0.5 flex h-4 w-4 items-center justify-center rounded-full border border-border bg-card"
                  aria-hidden
                >
                  {EventIcon ? (
                    <EventIcon className="h-2.5 w-2.5 text-muted-foreground" />
                  ) : (
                    <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" />
                  )}
                </span>
                <div className="flex flex-wrap items-baseline gap-x-3">
                  <time className="font-mono text-xs tabular-nums text-muted-foreground">
                    {formatClock(event.timestamp)}
                  </time>
                  <span className="text-sm">{event.label}</span>
                </div>
                <EventDetail event={event} />
              </li>
              );
            })}
          </ol>
        )}
      </section>
    </div>
  );
}

/** Shows only the small set of metadata that is safe and useful to display. */
function EventDetail({ event }: { event: TimelineEvent }) {
  const parts: string[] = [];

  const added = event.metadata?.lines_added;
  const removed = event.metadata?.lines_removed;
  if (typeof added === "number" || typeof removed === "number") {
    parts.push(`+${Number(added ?? 0)} / −${Number(removed ?? 0)}`);
  }

  const exitCode = event.metadata?.exit_code;
  if (typeof exitCode === "number") {
    parts.push(`exit ${exitCode}`);
  }

  // prompt_submitted carries length only -- there is no prompt text to leak here.
  const length = event.metadata?.length;
  if (typeof length === "number") {
    parts.push(`${length} chars`);
  }

  const tokens = event.metadata?.token_count;
  if (typeof tokens === "number") {
    parts.push(`${tokens.toLocaleString()} tokens`);
  }

  if (parts.length === 0) return null;

  return <p className="mt-1 font-mono text-xs text-muted-foreground">{parts.join(" · ")}</p>;
}
