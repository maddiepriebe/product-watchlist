import { formatCents } from "@/lib/format";

export type SparkPoint = {
  /** Observation time, epoch ms. */
  t: number;
  /** Integer cents. */
  cents: number;
};

type SparklineProps = {
  /** Points ordered by time ascending. */
  points: SparkPoint[];
  /** "Now" in epoch ms; the last price is held until here. */
  nowMs: number;
  /** Window length in days. */
  days?: number;
  className?: string;
};

const W = 320;
const H = 48;
const PAD_X = 4;
const PAD_Y = 6;

/**
 * Tiny step-line of a delta-logged price series: each price is held until the
 * next observation, and the last price is extended to now. Hairline stroke,
 * dot at the end. Coordinates are pixels only; prices stay integer cents.
 */
export function Sparkline({
  points,
  nowMs,
  days = 90,
  className = "",
}: SparklineProps) {
  if (points.length === 0) {
    return (
      <div
        role="img"
        aria-label="No price history yet"
        className={`h-12 w-full max-w-sm border-b border-dashed border-rule ${className}`}
      />
    );
  }

  const start = nowMs - days * 86_400_000;
  const prices = points.map((p) => p.cents);
  const min = Math.min(...prices);
  const max = Math.max(...prices);

  const x = (t: number) => {
    const clamped = Math.min(nowMs, Math.max(start, t));
    return PAD_X + ((clamped - start) / (nowMs - start)) * (W - 2 * PAD_X);
  };
  const y = (cents: number) =>
    min === max
      ? H / 2
      : PAD_Y + (1 - (cents - min) / (max - min)) * (H - 2 * PAD_Y);

  const coords: string[] = [];
  points.forEach((p, i) => {
    const px = x(p.t).toFixed(1);
    if (i > 0) {
      // hold the previous price until this observation
      coords.push(`${px},${y(points[i - 1].cents).toFixed(1)}`);
    }
    coords.push(`${px},${y(p.cents).toFixed(1)}`);
  });
  const last = points[points.length - 1];
  const endX = x(nowMs);
  const endY = y(last.cents);
  coords.push(`${endX.toFixed(1)},${endY.toFixed(1)}`);

  return (
    <svg
      role="img"
      aria-label={`${days}-day price history: low ${formatCents(min)}, high ${formatCents(max)}, now ${formatCents(last.cents)}`}
      viewBox={`0 0 ${W} ${H}`}
      className={`h-auto w-full max-w-sm overflow-visible ${className}`}
    >
      <polyline
        points={coords.join(" ")}
        fill="none"
        className="stroke-ink2"
        strokeWidth={1}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={endX} cy={endY} r={2.5} className="fill-ink" />
    </svg>
  );
}
