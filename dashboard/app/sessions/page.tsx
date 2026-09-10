import { ApiErrorNotice } from "@/components/api-error-notice";
import { SessionsTable } from "@/components/observatory/sessions-table";
import { fetchSessions } from "@/lib/api";

export const dynamic = "force-dynamic";

const AGENTS = ["all", "claude", "opencode", "kilocode"] as const;

export default async function SessionsPage({
  searchParams,
}: {
  searchParams: Promise<{ agent?: string; date?: string }>;
}) {
  const { agent, date } = await searchParams;
  const activeAgent = AGENTS.includes(agent as (typeof AGENTS)[number])
    ? (agent as string)
    : "all";

  let sessions;
  try {
    sessions = await fetchSessions({
      agent: activeAgent === "all" ? undefined : activeAgent,
      date: date || undefined,
    });
  } catch (error) {
    return <ApiErrorNotice message={(error as Error).message} />;
  }

  return (
    <div className="space-y-6">
      <div className="border-b pb-5">
        <h1 className="text-3xl font-semibold tracking-tight">Sessions</h1>
        <p className="mt-1 font-mono text-sm text-muted-foreground">
          Every recorded session across Claude Code, OpenCode & Kilo Code — newest first.
        </p>
      </div>
      <SessionsTable sessions={sessions} initialAgent={activeAgent} initialDate={date ?? ""} />
    </div>
  );
}
