import { formatCents } from "@/lib/format";
import { TONE_BG, toneForRank } from "@/lib/watchlist/verdict";

type PriceLadderProps = {
  /** Today's price, integer cents. */
  currentCents: number | null;
  /** 90-day low / high, integer cents. */
  lowCents: number | null;
  highCents: number | null;
  /** 30-day median, integer cents. Optional; the hairline is skipped if null. */
  medianCents: number | null;
  /** Percentile rank in the 90-day range, 0 (cheapest) to 100. */
  pctRank: number | null;
  className?: string;
};

/** Position along the track as a 0–100 percentage. Pixels only, never prices. */
function position(cents: number, low: number, high: number): number {
  const t = (cents - low) / (high - low);
  return Math.min(100, Math.max(0, t * 100));
}

/**
 * The signature component: a 90-day range with ticks at the low and high, a
 * hairline at the 30-day median, and a dot where today's price sits. The dot
 * is green at or under the 30th percentile, red at or over the 72nd, ink
 * between. Purely presentational.
 */
export function PriceLadder({
  currentCents,
  lowCents,
  highCents,
  medianCents,
  pctRank,
  className = "",
}: PriceLadderProps) {
  const hasRange =
    lowCents !== null && highCents !== null && highCents >= lowCents;

  if (!hasRange) {
    return (
      <div
        role="img"
        aria-label="No price history yet"
        className={`w-full ${className}`}
      >
        <div className="relative h-4">
          <div className="absolute inset-x-0 top-1/2 h-px bg-rule" />
        </div>
        <div className="mt-1 h-4" />
      </div>
    );
  }

  const flat = highCents === lowCents;
  const dotLeft =
    currentCents === null
      ? null
      : flat
        ? 50
        : position(currentCents, lowCents, highCents);
  const medianLeft =
    medianCents === null || flat
      ? null
      : position(medianCents, lowCents, highCents);
  // A flat series has no meaningful rank, so the dot stays neutral.
  const tone = flat ? "mid" : toneForRank(pctRank);

  const parts: string[] = [];
  if (currentCents !== null) parts.push(`Today ${formatCents(currentCents)}`);
  parts.push(
    flat
      ? `90-day price ${formatCents(lowCents)}, unchanged`
      : `90-day range ${formatCents(lowCents)}–${formatCents(highCents)}`,
  );
  if (medianCents !== null) parts.push(`typical ${formatCents(medianCents)}`);

  return (
    <div
      role="img"
      aria-label={parts.join(", ")}
      className={`w-full ${className}`}
    >
      <div className="relative mx-1 h-4">
        {/* track */}
        <div className="absolute inset-x-0 top-1/2 h-px bg-rule" />
        {/* low / high ticks (one tick when the series is flat) */}
        {flat ? (
          <div className="absolute top-1 bottom-1 left-1/2 w-px bg-ink3" />
        ) : (
          <>
            <div className="absolute top-1 bottom-1 left-0 w-px bg-ink3" />
            <div className="absolute top-1 right-0 bottom-1 w-px bg-ink3" />
          </>
        )}
        {/* 30-day median hairline */}
        {medianLeft !== null && (
          <div
            className="absolute top-0 bottom-0 w-px bg-ink2"
            style={{ left: `${medianLeft}%` }}
          />
        )}
        {/* today */}
        {dotLeft !== null && (
          <div
            className={`absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ${TONE_BG[tone]}`}
            style={{ left: `${dotLeft}%` }}
          />
        )}
      </div>
      <div
        aria-hidden="true"
        className="mt-1 flex justify-between font-mono text-xs text-ink3"
      >
        {flat ? (
          <span className="mx-auto">{formatCents(lowCents)}</span>
        ) : (
          <>
            <span>{formatCents(lowCents)}</span>
            <span>{formatCents(highCents)}</span>
          </>
        )}
      </div>
    </div>
  );
}
