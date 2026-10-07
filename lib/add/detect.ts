import type { ExtractOutcome } from "@/lib/worker";
import type { DetectResult } from "./types";

/**
 * Map a worker outcome onto what the wizard does next (docs/worker-api.md,
 * "App does" column). Pure so it can be checked without a worker.
 */
export function toDetectResult(outcome: ExtractOutcome): DetectResult {
  if (!outcome.reached) return { kind: "retry", message: outcome.message };

  const { status, message, source, variants } = outcome.response;
  switch (status) {
    case "ok":
      // The guard guarantees ok carries a source and at least one variant.
      if (!source) return { kind: "retry", message };
      return {
        kind: "detected",
        detected: {
          title: source.title,
          retailer: source.retailer,
          image_url: source.image_url,
          variants,
        },
      };
    case "no_price":
    case "not_implemented":
      // Manual fallback needs a normalized source to teach; without one, retry.
      return source ? { kind: "manual", message } : { kind: "retry", message };
    case "price_text_unparseable":
      return { kind: "manual", message };
    case "blocked":
    case "price_text_not_found":
      return source
        ? {
            kind: "unsupported",
            message,
            retailer: source.retailer,
            title: source.title,
          }
        : { kind: "retry", message };
    case "fetch_failed":
    case "invalid_url":
      return { kind: "retry", message };
  }
}
