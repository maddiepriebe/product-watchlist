import type { SourceStatus } from "@/lib/watchlist/types";

type StatusNoticeProps = {
  status: SourceStatus | null;
  hasFailingSource: boolean;
  /** Last scraper error for a failing source, when we have one. */
  lastError: string | null;
  hasPrice: boolean;
};

export const FAILING_COPY =
  "Checks are failing. The page loaded but no price was found; the layout probably changed.";
export const UNSUPPORTED_COPY = "We can't read prices from this retailer yet.";
export const FIRST_CHECK_COPY =
  "Checking for the first time — prices appear within a few minutes.";

/**
 * One line explaining why a row has no (or a stale) price. Returns null when
 * the row is healthy. Failing wins over everything: it needs the user's eye.
 */
export function StatusNotice({
  status,
  hasFailingSource,
  lastError,
  hasPrice,
}: StatusNoticeProps) {
  if (status === "failing" || hasFailingSource) {
    return (
      <p
        role="alert"
        className="border-l-2 border-high pl-3 text-sm text-high md:col-span-full"
      >
        {lastError ? (
          <>
            Checks are failing.{" "}
            <span className="font-mono text-xs break-words">{lastError}</span>
          </>
        ) : (
          FAILING_COPY
        )}
      </p>
    );
  }
  if (status === "unsupported") {
    return (
      <p className="border-l-2 border-rule pl-3 text-sm text-ink2 md:col-span-full">
        {UNSUPPORTED_COPY}
      </p>
    );
  }
  if (!hasPrice) {
    return (
      <p className="border-l-2 border-rule pl-3 text-sm text-ink2 md:col-span-full">
        {FIRST_CHECK_COPY}
      </p>
    );
  }
  return null;
}
