import { PlugZap } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { API_BASE } from "@/lib/api";

/**
 * Shown when the dashboard cannot reach the local API.
 *
 * The backend not running is the single most likely failure a user hits, and
 * PRD section 25 requires the dashboard to keep working and explain itself
 * rather than crash. This renders the fix, not a stack trace.
 */
export function ApiErrorNotice({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-6">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-destructive-foreground">
        <PlugZap className="h-4 w-4" aria-hidden />
        Cannot reach the local API
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">{message}</p>
      <p className="mt-4 text-xs text-muted-foreground">Start the backend with:</p>
      <pre className="mt-2 overflow-x-auto rounded-md border border-border bg-background p-3 font-mono text-xs">
        uv run uvicorn backend.api.main:app --port 3141
      </pre>
      <p className="mt-3 text-xs text-muted-foreground">
        Expecting it at <span className="font-mono">{API_BASE}</span>.
      </p>
    </div>
  );
}

/** Empty-state placeholder -- an honest "nothing yet", never fake sample data. */
export function EmptyState({
  icon: Icon,
  title,
  hint,
}: {
  icon?: LucideIcon;
  title: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-dashed border-border p-10 text-center">
      {Icon ? <Icon className="mx-auto h-6 w-6 text-muted-foreground" aria-hidden /> : null}
      <p className={Icon ? "mt-3 text-sm font-medium" : "text-sm font-medium"}>{title}</p>
      {hint ? <p className="mt-2 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
