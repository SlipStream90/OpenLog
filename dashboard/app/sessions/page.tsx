import { Inbox } from "lucide-react";
import Link from "next/link";

import { ApiErrorNotice, EmptyState } from "@/components/api-error-notice";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { fetchSessions, type SessionSummary } from "@/lib/api";
import { formatCost, formatDuration, formatNumber, formatTimestamp } from "@/lib/utils";

export const dynamic = "force-dynamic";

/** Sessions -- one row per session, columns per PRD section 14. */
export default async function SessionsPage() {
  let sessions: SessionSummary[];
  try {
    sessions = await fetchSessions();
  } catch (error) {
    return <ApiErrorNotice message={(error as Error).message} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Sessions</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {sessions.length === 0
            ? "No sessions recorded yet."
            : `${sessions.length} recorded session${sessions.length === 1 ? "" : "s"}.`}
        </p>
      </div>

      {sessions.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title="Nothing recorded yet"
          hint="Install the hooks (scripts/install_claude_hooks.py), then use Claude Code as normal. Sessions appear here automatically."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
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
              </TableRow>
            </TableHeader>
            <TableBody>
              {sessions.map((session) => (
                <TableRow key={session.id} className="group transition-colors">
                  <TableCell>
                    <Link
                      href={`/sessions/${encodeURIComponent(session.id)}`}
                      className="font-medium underline-offset-4 group-hover:underline"
                    >
                      {formatTimestamp(session.start_time)}
                    </Link>
                    <div className="font-mono text-xs text-muted-foreground">
                      {session.model ?? "unknown model"}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{session.agent}</TableCell>
                  <TableCell className="tabular-nums">
                    {formatDuration(session.duration_seconds)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatNumber(session.file_count)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatNumber(session.command_count)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatNumber(session.token_count)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatCost(session.estimated_cost)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums text-muted-foreground">
                    {/*
                      Productivity scoring is Milestone 3. The API always sends
                      null and this renders "N/A" -- never a stand-in number,
                      which users would read as real (PRD.md section 4).
                    */}
                    {session.productivity === null ? "N/A" : session.productivity.toFixed(0)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
