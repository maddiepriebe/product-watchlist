/**
 * Client for the Python worker's `POST /extract` (contract: docs/worker-api.md).
 *
 * Server-only: it reads WORKER_URL / WORKER_SHARED_SECRET, which must never be
 * NEXT_PUBLIC_. Call it only from Server Actions and Route Handlers.
 */
import {
  Constants,
  type Database,
  type Json,
} from "@/lib/supabase/database.types";

export type ExtractorKind = Database["public"]["Enums"]["extractor_kind"];

export const EXTRACT_STATUSES = [
  "ok",
  "no_price",
  "not_implemented",
  "blocked",
  "fetch_failed",
  "invalid_url",
  "price_text_unparseable",
  "price_text_not_found",
] as const;
export type ExtractStatus = (typeof EXTRACT_STATUSES)[number];

export interface WorkerSource {
  canonical_url: string;
  url_hash: string;
  retailer: string;
  title: string | null;
  image_url: string | null;
  extractor: ExtractorKind;
  extractor_config: Json;
  needs_browser: boolean;
}

export interface WorkerVariant {
  variant_key: string;
  size: string | null;
  color: string | null;
  /** Integer cents. */
  price_cents: number;
  currency: string;
  in_stock: boolean;
}

export interface ExtractResponse {
  status: ExtractStatus;
  message: string;
  source: WorkerSource | null;
  variants: WorkerVariant[];
}

/** Either the worker answered (any `status`), or we never got a usable answer. */
export type ExtractOutcome =
  | { reached: true; response: ExtractResponse }
  | { reached: false; message: string };

const TIMEOUT_MS = 25_000;

export const UNREACHABLE_MESSAGE =
  "We couldn't reach the price checker. Try again in a minute.";

function workerEnv(): { url: string; secret: string } {
  const url = process.env.WORKER_URL;
  const secret = process.env.WORKER_SHARED_SECRET;
  if (!url || !secret) {
    throw new Error(
      "Missing WORKER_URL or WORKER_SHARED_SECRET. " +
        "Copy .env.local.example to .env.local and set the price checker's URL and shared secret.",
    );
  }
  return { url: url.replace(/\/+$/, ""), secret };
}

// ---- runtime validation (hand-written; the worker is a separate deployable) ----

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isNullableString(v: unknown): v is string | null {
  return v === null || typeof v === "string";
}

function isExtractStatus(v: unknown): v is ExtractStatus {
  return (
    typeof v === "string" && (EXTRACT_STATUSES as readonly string[]).includes(v)
  );
}

function isExtractorKind(v: unknown): v is ExtractorKind {
  return (
    typeof v === "string" &&
    (Constants.public.Enums.extractor_kind as readonly string[]).includes(v)
  );
}

function isJson(v: unknown): v is Json {
  if (v === null) return true;
  switch (typeof v) {
    case "string":
    case "boolean":
      return true;
    case "number":
      return Number.isFinite(v);
    case "object":
      return Array.isArray(v)
        ? v.every(isJson)
        : Object.values(v).every((x) => x === undefined || isJson(x));
    default:
      return false;
  }
}

export function isWorkerSource(v: unknown): v is WorkerSource {
  return (
    isRecord(v) &&
    typeof v.canonical_url === "string" &&
    v.canonical_url !== "" &&
    typeof v.url_hash === "string" &&
    v.url_hash !== "" &&
    typeof v.retailer === "string" &&
    isNullableString(v.title) &&
    isNullableString(v.image_url) &&
    isExtractorKind(v.extractor) &&
    isRecord(v.extractor_config) &&
    isJson(v.extractor_config) &&
    typeof v.needs_browser === "boolean"
  );
}

export function isWorkerVariant(v: unknown): v is WorkerVariant {
  return (
    isRecord(v) &&
    typeof v.variant_key === "string" &&
    isNullableString(v.size) &&
    isNullableString(v.color) &&
    typeof v.price_cents === "number" &&
    Number.isSafeInteger(v.price_cents) &&
    v.price_cents >= 0 &&
    typeof v.currency === "string" &&
    v.currency.length === 3 &&
    typeof v.in_stock === "boolean"
  );
}

/**
 * Narrows an unknown JSON body to ExtractResponse. `ok` is held to a stricter
 * standard than the other statuses: it must carry a source and at least one
 * variant, with unique keys, or the app would be saving from a half answer.
 */
export function isExtractResponse(v: unknown): v is ExtractResponse {
  if (!isRecord(v)) return false;
  if (!isExtractStatus(v.status)) return false;
  if (typeof v.message !== "string") return false;
  if (v.source !== null && !isWorkerSource(v.source)) return false;
  if (!Array.isArray(v.variants) || !v.variants.every(isWorkerVariant)) {
    return false;
  }
  if (v.status === "ok") {
    if (v.source === null || v.variants.length === 0) return false;
    const keys = new Set(v.variants.map((x: WorkerVariant) => x.variant_key));
    if (keys.size !== v.variants.length) return false;
  }
  return true;
}

/**
 * Ask the worker what it can read from `url`. With `priceText` it runs the
 * manual fallback (the price the user sees on the page). Never throws for
 * network or response problems; throws only when the env vars are missing.
 */
export async function extractPrice(args: {
  url: string;
  priceText?: string;
}): Promise<ExtractOutcome> {
  const { url: base, secret } = workerEnv();
  const body: { url: string; price_text?: string } = { url: args.url };
  if (args.priceText !== undefined) body.price_text = args.priceText;

  let res: Response;
  try {
    res = await fetch(`${base}/extract`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${secret}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (err) {
    console.error("worker /extract: request failed", err);
    return { reached: false, message: UNREACHABLE_MESSAGE };
  }

  if (res.status === 401) {
    console.error("worker /extract: 401 — check WORKER_SHARED_SECRET");
    return {
      reached: false,
      message: "The price checker turned us away. Try again later.",
    };
  }
  if (!res.ok) {
    console.error(`worker /extract: HTTP ${res.status}`);
    return { reached: false, message: UNREACHABLE_MESSAGE };
  }

  let json: unknown;
  try {
    json = await res.json();
  } catch {
    console.error("worker /extract: response was not JSON");
    return { reached: false, message: UNREACHABLE_MESSAGE };
  }
  if (!isExtractResponse(json)) {
    console.error("worker /extract: response did not match the contract");
    return {
      reached: false,
      message: "The price checker sent an answer we couldn't read. Try again in a minute.",
    };
  }
  return { reached: true, response: json };
}
