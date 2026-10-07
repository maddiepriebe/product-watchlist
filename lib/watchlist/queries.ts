import { createClient } from "@/lib/supabase/server";
import type { SparkPoint } from "@/components/Sparkline";
import type {
  FailureByWatch,
  LinkedSource,
  SourcesByWatch,
  SeriesByVariant,
  WatchRowData,
  WatchlistData,
} from "./types";
import { DEFAULT_SORT, type SortKey } from "./sort";

const DAY_MS = 86_400_000;
const WINDOW_DAYS = 90;
/** PostgREST caps a response (1000 rows by default), so page the series. */
const PAGE_SIZE = 1000;

/**
 * Loads the dashboard: the `my_watchlist` view (all percentile/median math is
 * in SQL), then the raw 90-day price points for the visible variants (plotting
 * only), then last_error for any failing sources. Everything goes through
 * the user's RLS session.
 */
export async function loadWatchlist(
  sort: SortKey = DEFAULT_SORT,
): Promise<WatchlistData> {
  const supabase = await createClient();
  const nowMs = Date.now();

  const { data, error } = await orderBy(
    supabase.from("my_watchlist").select("*"),
    sort,
  );
  if (error) throw new Error(`Could not load your watchlist: ${error.message}`);

  const rows = (data ?? []).filter(
    (row): row is WatchRowData => row.watch_id !== null,
  );

  const [series, failures, sources] = await Promise.all([
    loadSeries(rows, nowMs),
    loadFailures(rows),
    loadSources(rows),
  ]);

  return { rows, series, failures, sources, nowMs };
}

/** Applies the chosen sort in SQL. watch_id is the final stable tiebreak. */
function orderBy<
  Q extends {
    order: (
      column: string,
      options: { ascending: boolean; nullsFirst: boolean },
    ) => Q;
  },
>(query: Q, sort: SortKey): Q {
  const asc = { ascending: true, nullsFirst: false };
  const desc = { ascending: false, nullsFirst: false };
  switch (sort) {
    case "oldest":
      return query.order("created_at", asc).order("watch_id", asc);
    case "name":
      return query.order("display_title", asc).order("watch_id", asc);
    case "best":
      // Lowest percentile rank first: today's price is cheapest vs its history.
      return query
        .order("pct_rank_90", asc)
        .order("display_title", asc)
        .order("watch_id", asc);
    case "newest":
      return query.order("created_at", desc).order("watch_id", asc);
  }
}

async function loadSeries(
  rows: WatchRowData[],
  nowMs: number,
): Promise<SeriesByVariant> {
  const variantIds = rows.flatMap((r) => (r.variant_id ? [r.variant_id] : []));
  const series: SeriesByVariant = {};
  if (variantIds.length === 0) return series;

  const supabase = await createClient();
  const since = new Date(nowMs - WINDOW_DAYS * DAY_MS).toISOString();

  for (let from = 0; ; from += PAGE_SIZE) {
    const { data, error } = await supabase
      .from("price_points")
      .select("variant_id, observed_at, price_cents")
      .in("variant_id", variantIds)
      .gt("observed_at", since)
      .order("variant_id", { ascending: true })
      .order("observed_at", { ascending: true })
      .range(from, from + PAGE_SIZE - 1);
    if (error) throw new Error(`Could not load price history: ${error.message}`);

    for (const p of data) {
      const point: SparkPoint = {
        t: Date.parse(p.observed_at),
        cents: p.price_cents,
      };
      (series[p.variant_id] ??= []).push(point);
    }
    if (data.length < PAGE_SIZE) break;
  }
  return series;
}

/** Every linked site for the visible watches, in one query. */
async function loadSources(rows: WatchRowData[]): Promise<SourcesByWatch> {
  const sources: SourcesByWatch = {};
  if (rows.length === 0) return sources;

  const supabase = await createClient();
  const { data, error } = await supabase
    .from("my_watch_sources")
    .select("*")
    .in(
      "watch_id",
      rows.map((r) => r.watch_id),
    )
    .order("added_at", { ascending: true })
    .order("source_id", { ascending: true });
  // Rows still render without the list; don't fail the page.
  if (error) return sources;

  for (const link of data) {
    if (link.watch_id === null || link.source_id === null) continue;
    const linked: LinkedSource = {
      ...link,
      watch_id: link.watch_id,
      source_id: link.source_id,
    };
    (sources[link.watch_id] ??= []).push(linked);
  }
  return sources;
}

async function loadFailures(rows: WatchRowData[]): Promise<FailureByWatch> {
  const failing = rows
    .filter((r) => r.has_failing_source || r.status === "failing")
    .map((r) => r.watch_id);
  const failures: FailureByWatch = {};
  if (failing.length === 0) return failures;

  const supabase = await createClient();
  const { data, error } = await supabase
    .from("watch_sources")
    .select("watch_id, product_sources!inner(status, last_error)")
    .in("watch_id", failing)
    .eq("product_sources.status", "failing");
  // The generic message still works without the detail; don't fail the page.
  if (error) return failures;

  for (const link of data) {
    const source = link.product_sources;
    // Keep the first non-empty error per watch.
    if (failures[link.watch_id] == null) {
      failures[link.watch_id] = source.last_error;
    }
  }
  return failures;
}
