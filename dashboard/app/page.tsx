import {
  AlertTriangle,
  Clock,
  DollarSign,
  FileEdit,
  FlaskConical,
  Terminal,
  Timer,
} from "lucide-react";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fetchStats, type Stats, type WatcherStatus } from "@/lib/api";
import { formatCost, formatDuration, formatNumber } from "@/lib/utils";

export const dynamic = "force-dynamic";

/**
 * Home -- today's summary cards.
 *
 * No charts (Milestone 4) and no productivity card: scoring is Milestone 3, and
 * PRD.md section 4 is explicit that showing a placeholder score would be worse
 * than showing nothing.
 */
export default async function HomePage() {
  let stats: Stats;
  try {
    stats = await fetchStats();
  } catch (error) {
    return <ApiErrorNotice message={(error as Error).message} />;
  }

  const cards = [
    { label: "Coding time", value: formatDuration(stats.coding_time_seconds), icon: Timer },
    { label: "Sessions", value: formatNumber(stats.session_count), icon: Clock },
    { label: "Files changed", value: formatNumber(stats.files_changed_count), icon: FileEdit },
    {
      label: "Estimated cost",
      value: formatCost(stats.estimated_cost),
      icon: DollarSign,
      // Without a pricing table the cost is genuinely unknown, and the card says
      // so rather than implying the day really cost $0.00.
      note: stats.cost_is_estimated ? undefined : "No pricing configured",
    },
    { label: "Commands", value: formatNumber(stats.command_count), icon: Terminal },
    { label: "Tests", value: formatNumber(stats.test_count), icon: FlaskConical },
  ];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Today</h1>
        <p className="mt-1 text-sm text-muted-foreground">{stats.date}</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card, index) => (
          <Card
            key={card.label}
            className="animate-in fade-in-0 slide-in-from-bottom-1 duration-300 fill-mode-both"
            style={{ animationDelay: `${index * 40}ms` }}
          >
            <CardHeader className="pb-2">
              <CardTitle>
                <card.icon className="h-3.5 w-3.5" aria-hidden />
                {card.label}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="font-mono text-3xl font-semibold tabular-nums tracking-tight">
                {card.value}
              </p>
              {card.note ? (
                <p className="mt-1 text-xs text-muted-foreground">{card.note}</p>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>

      <WatcherHealth watchers={stats.watchers} />
    </div>
  );
}

/**
 * Surfaces telemetry watcher failures in the UI.
 *
 * This is PRD section 25's "notify the user in the UI" clause: when a watcher
 * dies, the dashboard keeps working, and the user finds out here instead of
 * silently seeing numbers stop moving.
 */
function WatcherHealth({ watchers }: { watchers: Record<string, WatcherStatus> }) {
  const entries = Object.entries(watchers);
  if (entries.length === 0) return null;

  const degraded = entries.filter(([, w]) => w.status !== "running");
  if (degraded.length === 0) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />
        Telemetry watchers running: {entries.map(([name]) => name).join(", ")}.
      </p>
    );
  }

  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <AlertTriangle className="h-4 w-4 text-destructive" aria-hidden />
        Telemetry degraded
      </h2>
      <ul className="mt-2 space-y-1">
        {degraded.map(([name, watcher]) => (
          <li key={name} className="text-xs text-muted-foreground">
            <span className="font-mono">{name}</span>: {watcher.status}
            {watcher.last_error ? ` — ${watcher.last_error}` : null}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted-foreground">
        Collection is affected, but the dashboard and your coding session are not.
      </p>
    </div>
  );
}
