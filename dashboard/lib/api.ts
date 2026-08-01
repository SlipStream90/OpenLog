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
  /** Always null until Milestone 3. The UI renders "N/A", never a number. */
  productivity: number | null;
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

export async function fetchSessions(): Promise<SessionSummary[]> {
  const body = await getJson<{ sessions: SessionSummary[] }>("/sessions");
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
