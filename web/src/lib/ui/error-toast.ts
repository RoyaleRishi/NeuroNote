/**
 * Minimal user-facing error reporter.  Today this just logs to console under
 * a single tag (so production logs from the app itself are filterable) and
 * could later be wired to a toast component without touching call sites.
 */
export function reportUserError(scope: string, err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
    // eslint-disable-next-line no-console
    console.warn(`[neuronote:${scope}] ${message}`);
  }
}
