/**
 * Plain-language verdict for a watch, derived from where today's price sits in
 * its own 90-day history (`pct_rank_90`: 0 = cheapest in the window, 100 =
 * dearest). It is never derived from "discount off list price".
 *
 * Shared by PriceLadder (dot color) and WatchRow (verdict text) so the two
 * can't disagree.
 */

/** Rank at or under this is "cheap for this item". */
export const CHEAP_MAX_RANK = 30;
/** Rank at or over this is "above its usual price". */
export const HIGH_MIN_RANK = 72;

export type Tone = "low" | "mid" | "high";

export type VerdictKey = "at-low" | "cheap" | "mid" | "above";

export type Verdict = {
  key: VerdictKey;
  label: string;
  tone: Tone;
};

export type VerdictInput = {
  currentCents: number | null;
  lowCents: number | null;
  pctRank: number | null;
};

/** Tailwind classes per tone. Full strings so Tailwind's scanner sees them. */
export const TONE_TEXT: Record<Tone, string> = {
  low: "text-low",
  mid: "text-ink",
  high: "text-high",
};

export const TONE_BG: Record<Tone, string> = {
  low: "bg-low",
  mid: "bg-ink",
  high: "bg-high",
};

/** Color bucket for a percentile rank. Unknown rank reads as neutral. */
export function toneForRank(pctRank: number | null): Tone {
  if (pctRank === null || Number.isNaN(pctRank)) return "mid";
  if (pctRank <= CHEAP_MAX_RANK) return "low";
  if (pctRank >= HIGH_MIN_RANK) return "high";
  return "mid";
}

/**
 * Returns null when there is no current price, or no way to place it
 * (no rank and not at the low) — callers then show no verdict at all.
 */
export function verdictFor({
  currentCents,
  lowCents,
  pctRank,
}: VerdictInput): Verdict | null {
  if (currentCents === null) return null;

  if (lowCents !== null && currentCents <= lowCents) {
    return { key: "at-low", label: "At its 90-day low", tone: "low" };
  }
  if (pctRank === null || Number.isNaN(pctRank)) return null;

  if (pctRank <= CHEAP_MAX_RANK) {
    return { key: "cheap", label: "Cheap for this item", tone: "low" };
  }
  if (pctRank < HIGH_MIN_RANK) {
    return { key: "mid", label: "Sitting mid-range", tone: "mid" };
  }
  return { key: "above", label: "Above its usual price", tone: "high" };
}
