/**
 * Input parsing for alert rules. String math only: no float ever touches a
 * price. Pure, so it is unit-testable.
 */

/** Postgres `integer` ceiling; alert_below_cents is an int4 column. */
const MAX_INT4 = 2_147_483_647;

/**
 * "250", "$249.99", "1,299.5", ".99" -> integer cents. Returns null for
 * anything else (empty, negative, 3+ decimals, letters, too large).
 */
export function parseMoneyToCents(input: string): number | null {
  const cleaned = input.trim().replace(/^\$\s*/, "").replace(/,/g, "");
  const match = /^(\d*)(?:\.(\d{1,2}))?$/.exec(cleaned);
  if (!match) return null;
  const [, whole, frac = ""] = match;
  if (whole === "" && frac === "") return null;
  if (whole.length > 10) return null;

  const cents = Number(whole === "" ? "0" : whole) * 100 + Number(frac.padEnd(2, "0"));
  return cents <= MAX_INT4 ? cents : null;
}

/**
 * "10", "12.5", "7.25%" -> percent as a number with at most 2 decimals, in
 * the range 0 < x <= 99.99 (the column is numeric(5,2)). Returns null
 * otherwise. Built from the digits as a string, never by arithmetic on floats.
 */
export function parsePct(input: string): number | null {
  const cleaned = input.trim().replace(/\s*%$/, "");
  const match = /^(\d{1,2})(?:\.(\d{1,2}))?$/.exec(cleaned);
  if (!match) return null;
  const [, whole, frac = ""] = match;
  const hundredths = Number(whole) * 100 + Number(frac.padEnd(2, "0"));
  if (hundredths <= 0 || hundredths > 9999) return null;
  return Number(frac === "" ? whole : `${whole}.${frac}`);
}
