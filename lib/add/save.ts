/**
 * Database side of saving a product. Every call runs as the signed-in user
 * through RLS; nothing here can write a price (that is the worker's job).
 */
import type { SupabaseClient } from "@supabase/supabase-js";
import type { Database } from "@/lib/supabase/database.types";
import type { WorkerSource } from "@/lib/worker";
import type { AlertRules } from "./rules";

type Client = SupabaseClient<Database>;
type Failure = { ok: false; message: string };

export const SAVE_FAILED_MESSAGE =
  "We couldn't save that. Try again in a minute.";
export const CAP_MESSAGE =
  "You've reached 100 linked links. Archive a watch or remove a link to add more.";

const UNIQUE_VIOLATION = "23505";

export function isCapError(error: { message: string }): boolean {
  return error.message.includes("linked-source limit reached");
}

/**
 * Find the global source row for this canonical URL, or create it. A source
 * created for an unsupported retailer is marked so the scheduler skips it.
 * A concurrent insert of the same URL loses on url_hash UNIQUE; we then read
 * the winner's row instead of failing.
 */
export async function findOrCreateSource(
  supabase: Client,
  userId: string,
  source: WorkerSource,
  unsupported: boolean,
): Promise<{ ok: true; id: string } | Failure> {
  const lookup = () =>
    supabase
      .from("product_sources")
      .select("id")
      .eq("url_hash", source.url_hash)
      .maybeSingle();

  const existing = await lookup();
  if (existing.error) {
    console.error("save: source lookup failed", existing.error);
    return { ok: false, message: SAVE_FAILED_MESSAGE };
  }
  if (existing.data) return { ok: true, id: existing.data.id };

  const insert: Database["public"]["Tables"]["product_sources"]["Insert"] = {
    canonical_url: source.canonical_url,
    url_hash: source.url_hash,
    retailer: source.retailer,
    title: source.title,
    image_url: source.image_url,
    extractor: source.extractor,
    extractor_config: source.extractor_config,
    needs_browser: source.needs_browser,
    created_by: userId,
    ...(unsupported && { status: "unsupported" as const }),
  };
  const created = await supabase
    .from("product_sources")
    .insert(insert)
    .select("id")
    .single();
  if (created.data) return { ok: true, id: created.data.id };

  if (created.error?.code === UNIQUE_VIOLATION) {
    const raced = await lookup();
    if (raced.data) return { ok: true, id: raced.data.id };
  }
  console.error("save: source insert failed", created.error);
  return { ok: false, message: SAVE_FAILED_MESSAGE };
}

/** Insert the user's watch with its alert rules. */
export async function createWatch(
  supabase: Client,
  userId: string,
  fields: {
    nickname: string | null;
    watchedVariantKeys: string[] | null;
    rules: AlertRules;
  },
): Promise<{ ok: true; id: string } | Failure> {
  const insert: Database["public"]["Tables"]["watches"]["Insert"] = {
    user_id: userId,
    nickname: fields.nickname,
    watched_variant_keys: fields.watchedVariantKeys,
    alert_below_cents: fields.rules.alertBelowCents,
    alert_pct_drop: fields.rules.alertPctDrop,
    alert_on_new_low: fields.rules.alertOnNewLow,
    alert_on_restock: fields.rules.alertOnRestock,
    channel: "email",
  };
  const { data, error } = await supabase
    .from("watches")
    .insert(insert)
    .select("id")
    .single();
  if (error || !data) {
    console.error("save: watch insert failed", error);
    return { ok: false, message: SAVE_FAILED_MESSAGE };
  }
  return { ok: true, id: data.id };
}

/**
 * Attach a source to a watch. `duplicate` means the pair already exists
 * (only reachable when linking to an existing watch).
 */
export async function linkSource(
  supabase: Client,
  watchId: string,
  sourceId: string,
): Promise<{ ok: true } | { ok: false; duplicate: boolean; message: string }> {
  const { error } = await supabase
    .from("watch_sources")
    .insert({ watch_id: watchId, source_id: sourceId });
  if (!error) return { ok: true };
  if (error.code === UNIQUE_VIOLATION) {
    return { ok: false, duplicate: true, message: "Already linked." };
  }
  if (isCapError(error)) {
    return { ok: false, duplicate: false, message: CAP_MESSAGE };
  }
  console.error("save: link insert failed", error);
  return { ok: false, duplicate: false, message: SAVE_FAILED_MESSAGE };
}
