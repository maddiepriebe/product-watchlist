import { createClient } from "@/lib/supabase/server";
import type { SparkPoint } from "@/components/Sparkline";
import type {
  FailureByWatch,
  SeriesByVariant,
  WatchRowData,
  WatchlistData,
} from "./types";

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
export async function loadWatchlist(): Promise<WatchlistData> {
  const supabase = await createClient();
  const nowMs = Date.now();

  const { data, error } = await supabase
    .from("my_watchlist")
    .select("*")
    .order("display_title", { ascending: true, nullsFirst: false });
  if (error) throw new Error(`Could not load your watchlist: ${error.message}`);

  const rows = (data ?? []).filter(
    (row): row is WatchRowData => row.watch_id !== null,
  );

  const [series, failures] = await Promise.all([
    loadSeries(rows, nowMs),
    loadFailures(rows),
  ]);

  return { rows, series, failures, nowMs };
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
