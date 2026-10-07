import Link from "next/link";
import { WatchRow } from "@/components/WatchRow";
import { SortControl } from "@/components/watchlist/SortControl";
import { loadWatchlist } from "@/lib/watchlist/queries";
import { parseSort } from "@/lib/watchlist/sort";
import { unarchiveWatch } from "./actions";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type SearchParams = Promise<{
  archived?: string | string[];
  error?: string | string[];
  sort?: string | string[];
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
  const sort = parseSort(first(params.sort));
  const { rows, series, failures, sources, nowMs } = await loadWatchlist(sort);

  return (
    <div className="mx-auto max-w-5xl">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <h1 className="text-xl font-medium text-ink">Watchlist</h1>
        {rows.length > 1 && <SortControl current={sort} />}
      </div>

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
              sources={sources[row.watch_id] ?? []}
              nowMs={nowMs}
              lastError={failures[row.watch_id] ?? null}
            />
          ))}
        </div>
      )}
    </div>
  );
}
