"use client";

import { useEffect } from "react";

/** Route-level error boundary: explain and offer a way back, never a blank page. */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Logged for local debugging only; nothing leaves the machine.
    console.error(error);
  }, [error]);

  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-6" role="alert">
      <h2 className="text-sm font-semibold">Something went wrong rendering this page</h2>
      <p className="mt-2 font-mono text-xs text-muted-foreground">
        {error.message || "Unknown error"}
      </p>
      <button
        type="button"
        onClick={() => reset()}
        className="mt-4 inline-flex items-center rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground hover:bg-primary/90"
      >
        Try again
      </button>
    </div>
  );
}
