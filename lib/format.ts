/**
 * Display formatting. Money is integer cents everywhere; these helpers use
 * integer/string math only, so no float ever touches a price.
 */

/** 24800 -> "$248.00", 123456789 -> "$1,234,567.89". USD only for now. */
export function formatCents(cents: number): string {
  const negative = cents < 0;
  const abs = Math.abs(Math.trunc(cents));
  const dollars = Math.trunc(abs / 100).toString();
  const rem = (abs % 100).toString().padStart(2, "0");
  const grouped = dollars.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "-" : ""}$${grouped}.${rem}`;
}

/** 24800 -> "248.00" (no symbol or grouping; for pre-filling inputs). */
export function formatCentsPlain(cents: number): string {
  const abs = Math.abs(Math.trunc(cents));
  return `${Math.trunc(abs / 100)}.${(abs % 100).toString().padStart(2, "0")}`;
}

/**
 * Short relative time: "just now", "5 min ago", "3 h ago", "2 d ago".
 * `nowMs` is passed in so rendering stays pure and testable.
 */
export function formatRelative(iso: string, nowMs: number): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "unknown";
  const secs = Math.max(0, Math.floor((nowMs - then) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}
