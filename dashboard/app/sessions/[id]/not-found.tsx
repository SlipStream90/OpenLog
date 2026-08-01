import Link from "next/link";

export default function SessionNotFound() {
  return (
    <div className="rounded-lg border border-dashed border-border p-10 text-center">
      <p className="text-sm font-medium">Session not found</p>
      <p className="mt-2 text-xs text-muted-foreground">
        It may have been removed, or the link may be stale.
      </p>
      <Link href="/sessions" className="mt-4 inline-block text-xs underline">
        Back to all sessions
      </Link>
    </div>
  );
}
