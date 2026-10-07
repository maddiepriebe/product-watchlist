import type { SaveInput } from "./types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(v: string): boolean {
  return UUID.test(v);
}

/**
 * Server Actions are plain POST endpoints; TypeScript's view of the argument
 * is a hope, not a fact. Check the shape before trusting any field.
 */
export function isSaveInput(v: unknown): v is SaveInput {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  const alert = o.alert as Record<string, unknown> | null | undefined;
  return (
    typeof o.url === "string" &&
    (o.priceText === null || typeof o.priceText === "string") &&
    (o.mode === "confirmed" || o.mode === "unsupported") &&
    (o.watchedVariantKeys === null ||
      (Array.isArray(o.watchedVariantKeys) &&
        o.watchedVariantKeys.every((k) => typeof k === "string"))) &&
    typeof o.nickname === "string" &&
    (o.watchId === null || typeof o.watchId === "string") &&
    typeof alert === "object" &&
    alert !== null &&
    typeof alert.below === "string" &&
    typeof alert.pctDrop === "string" &&
    typeof alert.onNewLow === "boolean" &&
    typeof alert.onRestock === "boolean"
  );
}
