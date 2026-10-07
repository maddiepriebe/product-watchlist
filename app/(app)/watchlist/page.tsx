import { WatchRow } from "@/components/WatchRow";
import { loadWatchlist } from "@/lib/watchlist/queries";

export default async function WatchlistPage() {
  const { rows, series, nowMs } = await loadWatchlist();

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-xl font-medium text-ink">Watchlist</h1>
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
