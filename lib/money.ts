/**
 * Money input parsing. Pure string math — no floats — so "19.99" can never
 * become 1998.9999999999998 cents.
 */

/** Postgres `integer` ceiling; DB cents columns are int4. */
const MAX_CENTS = 2_147_483_647;

/**
 * "$249.99" → 24999, "250" → 25000, "1,250.5" → 125050, ".99" → 99.
 * Returns null for anything ambiguous or out of range: empty, negative,
 * letters, a second currency symbol, more than two decimals, malformed
 * thousands separators ("1,25"), or a value beyond the integer column.
 */
export function parseMoneyToCents(input: string): number | null {
  const s = input.trim().replace(/^\$\s*/, "");
  const match = /^(\d{1,3}(?:,\d{3})+|\d+)?(?:\.(\d{1,2}))?$/.exec(s);
  if (!match) return null;
  const [, whole, frac] = match;
  if (whole === undefined && frac === undefined) return null;

  const dollars = whole === undefined ? 0 : Number(whole.replaceAll(",", ""));
  const cents = frac === undefined ? 0 : Number(frac.padEnd(2, "0"));
  const total = dollars * 100 + cents;
  return Number.isSafeInteger(total) && total <= MAX_CENTS ? total : null;
}
