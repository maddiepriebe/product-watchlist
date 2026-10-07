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

const moneyFormatters = new Map<string, Intl.NumberFormat>();

function moneyFormatter(currency: string): Intl.NumberFormat {
  let fmt = moneyFormatters.get(currency);
  if (!fmt) {
    fmt = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    moneyFormatters.set(currency, fmt);
  }
  return fmt;
}

/** 29800 → "$298.00". */
export function formatMoney(cents: number, currency = "USD"): string {
  return moneyFormatter(currency).format(cents / 100);
}

/** Signed money delta: -1250 → "−$12.50", 900 → "+$9.00", 0 → "$0.00". */
export function formatMoneyDelta(cents: number, currency = "USD"): string {
  if (cents === 0) return formatMoney(0, currency);
  const sign = cents < 0 ? "−" : "+";
  return sign + formatMoney(Math.abs(cents), currency);
}

/** 12.345 → "12%"; 2.5 with digits=1 → "2.5%". */
export function formatPercent(value: number, digits = 0): string {
  return `${value.toFixed(digits)}%`;
}

/** Signed percent change from `from` to `to`: (8000, 10000) → "+25%". */
export function formatPercentChange(from: number, to: number): string {
  if (from === 0) return "—";
  const pct = ((to - from) / from) * 100;
  const rounded = Math.round(pct);
  if (rounded === 0) return "0%";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded)}%`;
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "3 hours ago", "in 2 days", "just now". */
export function formatRelativeTime(
  iso: string | Date,
  now: Date = new Date(),
): string {
  const then = typeof iso === "string" ? new Date(iso) : iso;
  const seconds = Math.round((then.getTime() - now.getTime()) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 60) return "just now";
  for (const [unit, size] of UNITS) {
    if (abs >= size) return relative.format(Math.round(seconds / size), unit);
  }
  return "just now";
}
