import Link from "next/link";
import { PriceLadder } from "@/components/PriceLadder";
import { Sparkline, type SparkPoint } from "@/components/Sparkline";
import { formatCents, formatRelative } from "@/lib/format";
import type { WatchRowData } from "@/lib/watchlist/types";
import { TONE_TEXT, verdictFor } from "@/lib/watchlist/verdict";

type WatchRowProps = {
  row: WatchRowData;
  /** 90-day series for this row's current variant. */
  points: SparkPoint[];
  nowMs: number;
};

function describeVariant(key: string | null): string | null {
  if (!key) return null;
  const parts = key.split("|").filter((part) => part !== "");
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** Plain-language summary of the alert rule, one clause per active rule. */
function ruleSummary(row: WatchRowData): string[] {
  const clauses: string[] = [];
  if (row.alert_below_cents !== null) {
    clauses.push(`Price at or below ${formatCents(row.alert_below_cents)}`);
  }
  if (row.alert_pct_drop !== null) {
    clauses.push(`Drops ${row.alert_pct_drop}% below the 30-day median`);
  }
  if (row.alert_on_new_low) clauses.push("New 90-day low");
  if (row.alert_on_restock) clauses.push("Back in stock");
  return clauses;
}

export function WatchRow({ row, points, nowMs }: WatchRowProps) {
  const title = row.display_title ?? "Untitled product";
  const variant = describeVariant(row.current_variant_key);
  const sourceCount = row.source_count ?? 1;
  const verdict = verdictFor({
    currentCents: row.current_cents,
    lowCents: row.low_90_cents,
    pctRank: row.pct_rank_90,
  });
  const rules = ruleSummary(row);

  return (
    <details className="group border-b border-rule bg-surface first:border-t">
      <summary className="grid cursor-pointer list-none gap-x-6 gap-y-3 px-4 py-4 md:grid-cols-[minmax(0,2fr)_10rem_minmax(0,2fr)_6rem_1rem] md:items-center [&::-webkit-details-marker]:hidden">
        <div className="min-w-0">
          <div className="truncate font-medium text-ink">{title}</div>
          <div className="mt-0.5 truncate text-sm text-ink2">
            {row.retailer}
            {sourceCount > 1 && (
              <span className="font-mono"> · {sourceCount} sources</span>
            )}
            {variant && <span> · {variant}</span>}
          </div>
        </div>

        <div>
          <div className="font-mono text-lg text-ink">
            {row.current_cents !== null ? formatCents(row.current_cents) : "—"}
          </div>
          {verdict && (
            <div className={`text-sm ${TONE_TEXT[verdict.tone]}`}>
              {verdict.label}
            </div>
          )}
        </div>

        <PriceLadder
          currentCents={row.current_cents}
          lowCents={row.low_90_cents}
          highCents={row.high_90_cents}
          medianCents={row.median_30_cents}
          pctRank={row.pct_rank_90}
        />

        <div className="font-mono text-xs text-ink3">
          {row.last_checked_at
            ? formatRelative(row.last_checked_at, nowMs)
            : "never"}
        </div>

        <svg
          aria-hidden="true"
          viewBox="0 0 10 10"
          className="hidden size-2.5 text-ink3 transition-transform group-open:rotate-90 md:block"
        >
          <path
            d="M3 1l4 4-4 4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.25"
          />
        </svg>
      </summary>

      <div className="grid gap-6 border-t border-rule px-4 py-4 md:grid-cols-2">
        <div>
          <h3 className="text-sm text-ink3">Last 90 days</h3>
          <div className="mt-2">
            <Sparkline points={points} nowMs={nowMs} />
          </div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {row.canonical_url && (
              <a
                href={row.canonical_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-ink2 underline underline-offset-4 hover:text-ink"
              >
                View at {row.retailer}
              </a>
            )}
            <Link
              href={`/add?watch=${row.watch_id}`}
              className="text-ink2 underline underline-offset-4 hover:text-ink"
            >
              Link another retailer
            </Link>
          </div>
        </div>

        <div>
          <h3 className="text-sm text-ink3">Alert rule</h3>
          {rules.length > 0 ? (
            <ul className="mt-2 space-y-1 text-sm text-ink">
              {rules.map((clause) => (
                <li key={clause}>{clause}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-ink2">No alerts set.</p>
          )}
        </div>
      </div>
    </details>
  );
}
