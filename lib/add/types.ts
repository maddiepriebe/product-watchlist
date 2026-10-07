/**
 * Shapes that cross the Server Action boundary. Deliberately a subset of the
 * worker's response: url_hash, extractor and extractor_config never reach the
 * browser, so there is nothing for the client to tamper with and send back.
 */

import type { AlertRulesInput } from "./rules";

export interface DetectedVariant {
  variant_key: string;
  size: string | null;
  color: string | null;
  /** Integer cents. */
  price_cents: number;
  currency: string;
  in_stock: boolean;
}

export interface Detected {
  title: string | null;
  retailer: string;
  image_url: string | null;
  variants: DetectedVariant[];
  /** The variant the pasted URL points at (one of `variants`), or null. */
  url_variant_key: string | null;
}

export type DetectResult =
  /** The worker read a price with an explicit path; show it for confirmation. */
  | { kind: "detected"; detected: Detected }
  /** No price found (or the user's text needs another try): ask for the price text. */
  | { kind: "manual"; message: string }
  /** We can't read this retailer; the user may keep watching it as unsupported. */
  | {
      kind: "unsupported";
      message: string;
      retailer: string;
      title: string | null;
    }
  /** Transient or unusable input; stay put and let the user try again. */
  | { kind: "retry"; message: string };

export interface SaveInput {
  url: string;
  /** The price text that produced the confirmed result; null for plain detection. */
  priceText: string | null;
  /** "unsupported" = the user chose "Keep watching anyway". */
  mode: "confirmed" | "unsupported";
  /** null = watch every variant. */
  watchedVariantKeys: string[] | null;
  nickname: string;
  alert: AlertRulesInput;
  /** Link the source to this existing watch instead of creating one. */
  watchId: string | null;
}

export type SaveResult =
  | { ok: true; watchId: string }
  | { ok: false; message: string };
