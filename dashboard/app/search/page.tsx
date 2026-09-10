import Link from "next/link";

import { ApiErrorNotice } from "@/components/api-error-notice";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { searchAll } from "@/lib/api";
import { formatTimestamp } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const query = (q ?? "").trim();

  if (!query) {
    return (
      <div className="space-y-6">
        <h1 className="text-3xl font-semibold tracking-tight">Search</h1>
        <p className="font-mono text-sm text-muted-foreground">
          Use the search box above to look through filenames, commands and sessions.
        </p>
      </div>
    );
  }

  let results;
  try {
    results = await searchAll(query);
  } catch (error) {
    return <ApiErrorNotice message={(error as Error).message} />;
  }

  const empty =
    results.files.length === 0 &&
    results.commands.length === 0 &&
    results.sessions.length === 0;

  return (
    <div className="space-y-6">
      <div className="border-b pb-5">
        <h1 className="text-3xl font-semibold tracking-tight">
          Results for <span className="font-mono text-primary">“{results.query}”</span>
        </h1>
        <p className="mt-1 font-mono text-sm text-muted-foreground">
          {results.files.length} files • {results.commands.length} commands •{" "}
          {results.sessions.length} sessions
        </p>
      </div>

      {empty && (
        <p className="rounded-xl border border-dashed p-10 text-center font-mono text-sm text-muted-foreground">
          Nothing matched “{results.query}”.
        </p>
      )}

      {results.sessions.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">Sessions</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {results.sessions.map((s) => (
                <li key={s.id} className="flex items-baseline justify-between gap-2 font-mono text-xs">
                  <Link href={`/sessions/${encodeURIComponent(s.id)}`} className="truncate text-primary hover:underline">
                    {s.id}
                  </Link>
                  <span className="shrink-0 text-muted-foreground">
                    {s.agent} • {formatTimestamp(s.start_time)}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {results.files.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">Files</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {results.files.map((f) => (
                <li key={f} className="truncate font-mono text-xs" title={f}>{f}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {results.commands.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">Commands</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {results.commands.map((c, i) => (
                <li key={`${c.session_id}-${i}`} className="flex items-baseline justify-between gap-2 font-mono text-xs">
                  <span className="truncate" title={c.command}>{c.command}</span>
                  <span className="shrink-0 text-muted-foreground">
                    exit {c.exit_code ?? "?"} • {formatTimestamp(c.timestamp)}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
