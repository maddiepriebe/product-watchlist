"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { parseMoneyToCents, parsePct } from "@/lib/watchlist/parse";
import type { RuleFormState, WatchUpdate } from "@/lib/watchlist/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MUTE_DAYS = 7;
const DAY_MS = 86_400_000;

function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function watchId(formData: FormData): string | null {
  const id = text(formData, "watch_id");
  return UUID.test(id) ? id : null;
}

/**
 * Updates one watch through the user's RLS session. RLS filters other users'
 * rows silently, so we ask for the row back to tell "updated" from "not yours".
 * Returns an error message, or null on success.
 */
async function updateWatch(
  id: string,
  patch: WatchUpdate,
): Promise<string | null> {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return "Your session expired. Sign in again.";

  const { data, error } = await supabase
    .from("watches")
    .update(patch)
    .eq("id", id)
    .select("id");
  if (error) return "Couldn't save that change. Try again.";
  if (data.length === 0) return "That watch no longer exists. Refresh the page.";
  return null;
}

/** For one-click actions without a form state: surface failures in a banner. */
function failTo(message: string): never {
  redirect(`/watchlist?error=${encodeURIComponent(message)}`);
}

export async function updateAlertRules(
  _prev: RuleFormState,
  formData: FormData,
): Promise<RuleFormState> {
  const id = watchId(formData);
  if (!id) return { status: "error", message: "Couldn't find that watch. Refresh the page." };

  const belowRaw = text(formData, "alert_below").trim();
  const pctRaw = text(formData, "alert_pct_drop").trim();
  const fieldErrors: NonNullable<RuleFormState["fieldErrors"]> = {};

  // Empty means "rule off".
  let belowCents: number | null = null;
  if (belowRaw !== "") {
    belowCents = parseMoneyToCents(belowRaw);
    if (belowCents === null || belowCents === 0) {
      fieldErrors.below = "Enter a price above $0, like 250 or $249.99.";
    }
  }

  let pct: number | null = null;
  if (pctRaw !== "") {
    pct = parsePct(pctRaw);
    if (pct === null) {
      fieldErrors.pct = "Enter a percentage above 0 and up to 99.99.";
    }
  }

  if (fieldErrors.below || fieldErrors.pct) {
    return { status: "error", message: "Fix the highlighted fields.", fieldErrors };
  }

  const failure = await updateWatch(id, {
    alert_below_cents: belowCents,
    alert_pct_drop: pct,
    alert_on_new_low: formData.get("alert_on_new_low") === "on",
    alert_on_restock: formData.get("alert_on_restock") === "on",
  });
  if (failure) return { status: "error", message: failure };

  revalidatePath("/watchlist");
  return { status: "saved", message: "Saved." };
}

export async function muteWatch(formData: FormData): Promise<void> {
  const id = watchId(formData);
  if (!id) failTo("Couldn't find that watch. Refresh the page.");

  const until = new Date(Date.now() + MUTE_DAYS * DAY_MS).toISOString();
  const failure = await updateWatch(id, { muted_until: until });
  if (failure) failTo(failure);
  revalidatePath("/watchlist");
}

export async function archiveWatch(formData: FormData): Promise<void> {
  const id = watchId(formData);
  if (!id) failTo("Couldn't find that watch. Refresh the page.");

  const failure = await updateWatch(id, {
    archived_at: new Date().toISOString(),
  });
  if (failure) failTo(failure);
  revalidatePath("/watchlist");
  // The page shows an "Archived. Undo" banner keyed by this id.
  redirect(`/watchlist?archived=${id}`);
}

export async function unarchiveWatch(formData: FormData): Promise<void> {
  const id = watchId(formData);
  if (!id) failTo("Couldn't find that watch. Refresh the page.");

  const failure = await updateWatch(id, { archived_at: null });
  if (failure) failTo(failure);
  revalidatePath("/watchlist");
  redirect("/watchlist");
}

export async function unmuteWatch(formData: FormData): Promise<void> {
  const id = watchId(formData);
  if (!id) failTo("Couldn't find that watch. Refresh the page.");

  const failure = await updateWatch(id, { muted_until: null });
  if (failure) failTo(failure);
  revalidatePath("/watchlist");
}
