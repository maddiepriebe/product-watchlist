"use server";

import { redirect } from "next/navigation";
import { toDetectResult } from "@/lib/add/detect";
import type { DetectResult } from "@/lib/add/types";
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
