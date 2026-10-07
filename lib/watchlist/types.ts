import type { Database } from "@/lib/supabase/database.types";
import type { SparkPoint } from "@/components/Sparkline";

type PublicSchema = Database["public"];

/** One row of the `my_watchlist` view (every column is nullable in views). */
export type WatchlistViewRow = PublicSchema["Views"]["my_watchlist"]["Row"];

/** A view row that is known to carry its watch id. */
export type WatchRowData = WatchlistViewRow & { watch_id: string };

export type WatchUpdate = PublicSchema["Tables"]["watches"]["Update"];

export type SourceStatus = PublicSchema["Enums"]["source_status"];

/** 90-day price series keyed by variant id, oldest first. */
export type SeriesByVariant = Record<string, SparkPoint[]>;

/** State returned by the inline alert-rule form action. */
export type RuleFormState = {
  status: "idle" | "saved" | "error";
  message?: string;
  fieldErrors?: { below?: string; pct?: string };
};

export type WatchlistData = {
  rows: WatchRowData[];
  series: SeriesByVariant;
  /** Captured once at load so every row renders against the same "now". */
  nowMs: number;
};
