/**
 * Typed client for the local API (api_contracts.md).
 *
 * Every call targets localhost only. If you are adding a fetch to any other
 * origin, stop: this product must keep working with the network disabled
 * (PRD section 21).
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:3141";

export interface SessionSummary {
  id: string;
  agent: string;
  model: string | null;
  start_time: string;
  end_time: string | null;
  duration_seconds: number | null;
  file_count: number;
  command_count: number;
  token_count: number;
  estimated_cost: number;
  /** Deterministic 0-100 score, or null when the session has no evidence. Never a fabricated 0. */
  productivity: number | null;
  /** Per-factor reasons behind the score ("+10 session completed"). */
  productivity_reasons: string[];
}

export interface SessionDetail extends SessionSummary {
  test_pass_count: number;
  test_fail_count: number;
  commit_count: number;
}

export interface TimelineEvent {
  timestamp: string;
  event_type: string;
  label: string;
  file: string | null;
  metadata: Record<string, unknown>;
}

export interface WatcherStatus {
  status: string;
  last_success_at: string | null;
  last_error: string | null;
}

export interface Stats {
  date: string;
  coding_time_seconds: number;
  session_count: number;
  files_changed_count: number;
  estimated_cost: number;
  command_count: number;
  test_count: number;
  cost_is_estimated: boolean;
  watchers: Record<string, WatcherStatus>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Fetch a JSON endpoint.
 *
 * `no-store` because telemetry is written continuously -- a cached page would
 * show stale numbers immediately after a coding session, which is exactly when
 * the user opens the dashboard.
 */
async function getJson<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  } catch (cause) {
    // The backend simply not running is the most common failure here, and it
    // should read as a clear message rather than a Next.js error overlay.
    throw new ApiError(
      `Cannot reach the AI Observatory API at ${API_BASE}. Is the backend running?`,
      null,
    );
  }

  if (response.status === 404) {
    throw new ApiError("Not found", 404);
  }
  if (!response.ok) {
    throw new ApiError(`API returned ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

export async function fetchStats(): Promise<Stats> {
  return getJson<Stats>("/stats");
}

export async function fetchSessions(opts?: {
  agent?: string;
  date?: string;
}): Promise<SessionSummary[]> {
  const params = new URLSearchParams();
  if (opts?.agent) params.set("agent", opts.agent);
  if (opts?.date) params.set("date", opts.date);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  const body = await getJson<{ sessions: SessionSummary[] }>(`/sessions${suffix}`);
  return body.sessions;
}

export async function fetchSession(id: string): Promise<SessionDetail> {
  return getJson<SessionDetail>(`/session/${encodeURIComponent(id)}`);
}

export async function fetchTimeline(id: string): Promise<TimelineEvent[]> {
  const body = await getJson<{ session_id: string; events: TimelineEvent[] }>(
    `/timeline/${encodeURIComponent(id)}`,
  );
  return body.events;
}

export interface FileAggregate {
  filename: string;
  session_count: number;
  total_additions: number;
  total_deletions: number;
  total_modifications: number;
  last_modified: string | null;
}

export async function fetchFiles(): Promise<FileAggregate[]> {
  const body = await getJson<{ files: FileAggregate[] }>("/files");
  return body.files;
}

export interface ChartPoint {
  date: string;
  sessions: number;
  seconds: number;
  tokens: number;
  cost: number;
}

export async function fetchCharts(range: "7d" | "30d" = "7d"): Promise<ChartPoint[]> {
  const body = await getJson<{ range: string; points: ChartPoint[] }>(
    `/charts?range=${range}`,
  );
  return body.points;
}

export interface PromptStats {
  count: number;
  avg_length: number;
  max_length: number;
  long_count: number;
  short_count: number;
  per_day: { date: string; count: number; avg_length: number }[];
}

export async function fetchPromptStats(): Promise<PromptStats> {
  return getJson<PromptStats>("/analytics/prompts");
}

export interface CommandStats {
  total: number;
  succeeded: number;
  failed: number;
  fail_rate: number;
  git_count: number;
  build_count: number;
  top: { command: string; count: number; fail_count: number }[];
}

export async function fetchCommandStats(): Promise<CommandStats> {
  return getJson<CommandStats>("/analytics/commands");
}

export interface SearchResults {
  query: string;
  files: string[];
  commands: { command: string; session_id: string; timestamp: string; exit_code: number | null }[];
  sessions: { id: string; agent: string; start_time: string }[];
}

export async function searchAll(query: string): Promise<SearchResults> {
  return getJson<SearchResults>(`/search?q=${encodeURIComponent(query)}`);
}

/** Direct download URL for a table export (hits the local API, not Next). */
export function exportHref(
  table: "sessions" | "events" | "files" | "commands" | "prompts",
  format: "json" | "csv",
): string {
  return `${API_BASE}/export?table=${table}&format=${format}`;
}

export interface Recommendation {
  rule_id: string;
  severity: "warning" | "suggestion" | "info" | string;
  message: string;
  metric: Record<string, unknown>;
}

export async function fetchRecommendations(): Promise<Recommendation[]> {
  const body = await getJson<{ recommendations: Recommendation[] }>("/recommendations");
  return body.recommendations;
}
