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
  const { rows, series, nowMs } = await loadWatchlist();

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

      <div className="mt-6">
        {rows.map((row) => (
          <WatchRow
            key={row.watch_id}
            row={row}
            points={row.variant_id ? (series[row.variant_id] ?? []) : []}
            nowMs={nowMs}
          />
        ))}
      </div>
    </div>
  );
}
