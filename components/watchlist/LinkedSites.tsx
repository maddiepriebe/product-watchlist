import Link from "next/link";
import { formatCents } from "@/lib/format";
import type { LinkedSource } from "@/lib/watchlist/types";

type LinkedSitesProps = {
  watchId: string;
  sources: LinkedSource[];
};

/** One short line saying why a site has no trustworthy price, or null. */
function statusNote(source: LinkedSource): { text: string; bad: boolean } | null {
  switch (source.status) {
    case "failing":
      return { text: "Checks are failing", bad: true };
    case "unsupported":
      return { text: "We can't read prices here yet", bad: false };
    case "paused":
      return { text: "Checks are paused", bad: false };
    default:
      return source.current_cents === null
        ? { text: "Waiting for the first price", bad: false }
        : null;
  }
}

/**
 * Every retailer a watch is linked to, with each one's own current price.
 * The cheapest flag comes from SQL (`is_cheapest`); it is only shown when
 * there is more than one priced site to compare.
 */
export function LinkedSites({ watchId, sources }: LinkedSitesProps) {
  const pricedCount = sources.filter((s) => s.current_cents !== null).length;

  return (
    <div>
      <h3 className="text-sm text-ink3">Linked sites</h3>
      {sources.length > 0 && (
        <ul className="mt-2 border-t border-rule">
          {sources.map((source) => {
            const note = statusNote(source);
            const cheapest = source.is_cheapest === true && pricedCount > 1;
            return (
              <li
                key={source.source_id}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 gap-y-0.5 border-b border-rule py-2 text-sm"
              >
                <div className="min-w-0">
                  <span className="text-ink">{source.retailer}</span>
                  {cheapest && <span className="ml-2 text-low">Cheapest</span>}
                </div>
                <div className="text-right">
                  {source.current_cents !== null ? (
                    <span className="font-mono text-ink">
                      {formatCents(source.current_cents)}
                    </span>
                  ) : (
                    <span className="text-ink3">—</span>
                  )}
                </div>
                <div className="min-w-0 text-ink2">
                  {source.current_cents !== null && (
                    <span>
                      {source.in_stock === false ? "Out of stock" : "In stock"}
                    </span>
                  )}
                  {note && (
                    <span
                      className={
                        source.current_cents !== null
                          ? `ml-2 ${note.bad ? "text-high" : "text-ink2"}`
                          : note.bad
                            ? "text-high"
                            : "text-ink2"
                      }
                    >
                      {note.text}
                    </span>
                  )}
                </div>
                <div className="text-right">
                  {source.canonical_url && (
                    <a
                      href={source.canonical_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-ink2 underline underline-offset-4 hover:text-ink"
                    >
                      View
                      <span className="sr-only"> at {source.retailer}</span>
                    </a>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <Link
        href={`/add?watch=${watchId}`}
        className="mt-3 flex items-center justify-between gap-3 border border-rule px-3 py-2 text-sm text-ink hover:bg-ground"
        style={{ borderRadius: "var(--radius)" }}
      >
        <span>Found it somewhere else? Link another site</span>
        <span aria-hidden="true">→</span>
      </Link>
    </div>
  );
}
