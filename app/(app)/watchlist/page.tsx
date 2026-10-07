import Link from "next/link";
import { WatchRow } from "@/components/WatchRow";
import { loadWatchlist } from "@/lib/watchlist/queries";
import { unarchiveWatch } from "./actions";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type SearchParams = Promise<{
  archived?: string | string[];
  error?: string | string[];
}>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function WatchlistPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const archivedId = first(params.archived);
  const error = first(params.error);
  const { rows, series, failures, nowMs } = await loadWatchlist();

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-xl font-medium text-ink">Watchlist</h1>

      {error && (
        <p
          role="alert"
          className="mt-4 border border-rule bg-surface px-4 py-3 text-sm text-high"
          style={{ borderRadius: "var(--radius)" }}
        >
          {error}
        </p>
      )}

      {archivedId && UUID.test(archivedId) && (
        <form
          action={unarchiveWatch}
          role="status"
          className="mt-4 flex items-center gap-3 border border-rule bg-surface px-4 py-3 text-sm text-ink"
          style={{ borderRadius: "var(--radius)" }}
        >
          <input type="hidden" name="watch_id" value={archivedId} />
          <span>Archived.</span>
          <button
            type="submit"
            className="text-ink2 underline underline-offset-4 hover:text-ink"
          >
            Undo
          </button>
        </form>
      )}

      {rows.length === 0 ? (
        <div
          className="mt-6 border border-rule bg-surface px-6 py-10"
          style={{ borderRadius: "var(--radius)" }}
        >
          <p className="font-medium text-ink">Nothing on your watchlist yet.</p>
          <p className="mt-1 text-ink2">
            Paste a product link to start tracking its price.
          </p>
          <Link
            href="/add"
            className="mt-5 inline-block bg-ink px-3 py-2 text-sm text-surface"
            style={{ borderRadius: "var(--radius)" }}
          >
            Add a product
          </Link>
        </div>
      ) : (
        <div className="mt-6">
          {rows.map((row) => (
            <WatchRow
              key={row.watch_id}
              row={row}
              points={row.variant_id ? (series[row.variant_id] ?? []) : []}
              nowMs={nowMs}
              lastError={failures[row.watch_id] ?? null}
            />
          ))}
        </div>
      )}
    </div>
  );
}
