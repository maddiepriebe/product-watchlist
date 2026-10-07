/**
 * Display formatting. Inputs are integer cents and ISO timestamps straight
 * from the DB; nothing here does price math beyond dividing for display.
 */

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
