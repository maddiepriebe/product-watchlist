"use server";

import { redirect } from "next/navigation";
import { toDetectResult } from "@/lib/add/detect";
import { parseAlertRules } from "@/lib/add/rules";
import {
  createWatch,
  findOrCreateSource,
  linkSource,
  SAVE_FAILED_MESSAGE,
} from "@/lib/add/save";
import { isSaveInput, isUuid } from "@/lib/add/save-input";
import type { DetectResult, SaveFailure, SaveInput } from "@/lib/add/types";
import { createClient } from "@/lib/supabase/server";
import { extractPrice } from "@/lib/worker";

const MAX_URL_LENGTH = 2048;
const MAX_PRICE_TEXT_LENGTH = 64;

/** Server Actions are public POST endpoints: check the session every time. */
async function requireUser() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");
  return { supabase, user };
}

/** Trim and bound the URL. Real validation is the worker's (`invalid_url`). */
function cleanUrl(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const url = raw.trim();
  return url === "" || url.length > MAX_URL_LENGTH ? null : url;
}

function cleanPriceText(raw: unknown): string | null | undefined {
  if (raw === undefined || raw === null) return undefined;
  if (typeof raw !== "string") return null;
  const text = raw.trim();
  return text === "" || text.length > MAX_PRICE_TEXT_LENGTH ? null : text;
}

/**
 * Step 1 and the manual fallback: ask the worker what it can read. Writes
 * nothing. Returns only what the wizard shows, never the extractor details.
 */
export async function detectAction(input: {
  url: string;
  priceText?: string;
}): Promise<DetectResult> {
  await requireUser();

  const url = cleanUrl(input.url);
  if (!url) {
    return {
      kind: "retry",
      message: "Paste the full link to the product page.",
    };
  }
  const priceText = cleanPriceText(input.priceText);
  if (priceText === null) {
    return {
      kind: "manual",
      message: "Paste the price exactly as you see it, like $298.00.",
    };
  }

  return toDetectResult(await extractPrice({ url, priceText }));
}

const MAX_NICKNAME_LENGTH = 120;
const BAD_REQUEST = "That request didn't look right. Start again.";

function fail(message: string): SaveFailure {
  return { message };
}

/**
 * Final step. Nothing the browser sends about the product is trusted: the
 * worker is asked again, and the source row (url_hash, extractor, config) is
 * built from that fresh answer. The client contributes only choices the user
 * is entitled to make: which variants, the nickname, the alert rules, and the
 * price text, which the worker re-verifies against the page. No price is
 * written here; the scheduler's first check records the first price point.
 *
 * Returns only on failure. Success redirects to the watchlist.
 */
export async function saveAction(raw: SaveInput): Promise<SaveFailure> {
  const { supabase, user } = await requireUser();

  if (!isSaveInput(raw)) return fail(BAD_REQUEST);
  const url = cleanUrl(raw.url);
  const priceText = cleanPriceText(raw.priceText);
  if (!url || priceText === null) return fail(BAD_REQUEST);
  if (raw.watchId !== null && !isUuid(raw.watchId)) return fail(BAD_REQUEST);

  const parsed = parseAlertRules(raw.alert);
  if (!parsed.ok) return fail("Check the alert amounts and try again.");

  const nickname = raw.nickname.trim();
  if (nickname.length > MAX_NICKNAME_LENGTH) {
    return fail("Use a nickname of 120 characters or fewer.");
  }

  if (raw.watchId !== null) {
    // Select first so a guessed id gets a clear message, not an RLS error.
    // RLS already limits this to the user's own watches; the explicit
    // user_id filter keeps the intent visible.
    const { data: watch, error } = await supabase
      .from("watches")
      .select("id")
      .eq("id", raw.watchId)
      .eq("user_id", user.id)
      .is("archived_at", null)
      .maybeSingle();
    if (error) {
      console.error("save: watch lookup failed", error);
      return fail(SAVE_FAILED_MESSAGE);
    }
    if (!watch) {
      return fail("We couldn't find that watch. It may have been archived.");
    }
  }

  const outcome = await extractPrice({ url, priceText });
  if (!outcome.reached) return fail(outcome.message);
  const { status, message, source, variants } = outcome.response;

  let watchedVariantKeys: string[] | null = null;
  if (raw.mode === "confirmed") {
    if (status !== "ok" || !source) {
      return fail(
        `We couldn't read the price a second time. ${message} Start again to re-check it.`,
      );
    }
    // Variant choice belongs to the watch, so link mode ignores it.
    if (raw.watchedVariantKeys !== null && raw.watchId === null) {
      const known = new Set(variants.map((v) => v.variant_key));
      const chosen = new Set(raw.watchedVariantKeys);
      const valid =
        chosen.size > 0 &&
        chosen.size === raw.watchedVariantKeys.length &&
        raw.watchedVariantKeys.every((key) => known.has(key));
      if (!valid) {
        return fail(
          "Those options changed on the page. Start again to pick again.",
        );
      }
      watchedVariantKeys = raw.watchedVariantKeys;
    }
  } else {
    // "Keep watching anyway" is only offered for pages we can't read. If the
    // worker can read it now, the user should confirm a real price instead.
    if (status === "ok") {
      return fail(
        "We can read this page now. Start again to confirm the price.",
      );
    }
    if (
      !source ||
      (status !== "blocked" && status !== "price_text_not_found")
    ) {
      return fail(message);
    }
  }
  if (!source) return fail(SAVE_FAILED_MESSAGE);

  const sourceResult = await findOrCreateSource(
    supabase,
    user.id,
    source,
    raw.mode === "unsupported",
  );
  if (!sourceResult.ok) return fail(sourceResult.message);

  if (raw.watchId !== null) {
    // Link mode: the watch already exists and keeps its own rules.
    const linkedToExisting = await linkSource(
      supabase,
      raw.watchId,
      sourceResult.id,
    );
    if (!linkedToExisting.ok) {
      return fail(
        linkedToExisting.duplicate
          ? "Already linked. This watch already tracks that page."
          : linkedToExisting.message,
      );
    }
    redirect("/watchlist");
  }

  const watch = await createWatch(supabase, user.id, {
    nickname: nickname === "" ? null : nickname,
    watchedVariantKeys,
    rules: parsed.rules,
  });
  if (!watch.ok) return fail(watch.message);

  const linked = await linkSource(supabase, watch.id, sourceResult.id);
  if (!linked.ok) {
    // Don't leave an empty watch behind (the 100-link cap trips here).
    const { error } = await supabase
      .from("watches")
      .delete()
      .eq("id", watch.id);
    if (error) console.error("save: cleanup of empty watch failed", error);
    return fail(linked.message);
  }

  redirect("/watchlist");
}
