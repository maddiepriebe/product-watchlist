"use client";

import { useState } from "react";
import { formatMoney } from "@/lib/format";
import { parseAlertRules, type AlertRulesInput } from "@/lib/add/rules";
import type { DetectedVariant } from "@/lib/add/types";
import { inputClass, labelClass, primaryButtonClass } from "./ui";

export function AlertStep({
  email,
  watched,
  onSubmit,
  pending,
  error,
}: {
  email: string;
  /** Variants being watched, for the "currently" hint; null when unreadable. */
  watched: DetectedVariant[] | null;
  /** Called only with input that already passes parseAlertRules. */
  onSubmit: (input: AlertRulesInput) => void;
  pending: boolean;
  error: string | null;
}) {
  const [below, setBelow] = useState("");
  const [pctDrop, setPctDrop] = useState("");
  const [onNewLow, setOnNewLow] = useState(true);
  const [onRestock, setOnRestock] = useState(true);
  const [errors, setErrors] = useState<{ below?: string; pctDrop?: string }>(
    {},
  );

  const cheapest = watched?.length
    ? watched.reduce((a, b) => (b.price_cents < a.price_cents ? b : a))
    : null;

  function submit() {
    const input = { below, pctDrop, onNewLow, onRestock };
    const result = parseAlertRules(input);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    setErrors({});
    onSubmit(input);
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="flex flex-col gap-5"
    >
      {cheapest && (
        <p className="text-ink2">
          Lowest price right now:{" "}
          <span className="font-mono text-ink">
            {formatMoney(cheapest.price_cents, cheapest.currency)}
          </span>
        </p>
      )}

      <div className="flex flex-col gap-2">
        <label htmlFor="alert-below" className={labelClass}>
          Alert me below
        </label>
        <div className="flex items-center gap-2">
          <span className="font-mono text-ink2">$</span>
          <input
            id="alert-below"
            type="text"
            inputMode="decimal"
            autoComplete="off"
            placeholder="249.99"
            value={below}
            onChange={(event) => setBelow(event.target.value)}
            aria-describedby={errors.below ? "alert-below-error" : undefined}
            aria-invalid={errors.below ? true : undefined}
            className={`${inputClass} font-mono`}
          />
        </div>
        {errors.below && (
          <p id="alert-below-error" role="alert" className="text-high">
            {errors.below}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="alert-pct" className={labelClass}>
          Alert on a drop of this percent from its typical price (optional)
        </label>
        <div className="flex items-center gap-2">
          <input
            id="alert-pct"
            type="text"
            inputMode="decimal"
            autoComplete="off"
            placeholder="15"
            value={pctDrop}
            onChange={(event) => setPctDrop(event.target.value)}
            aria-describedby={errors.pctDrop ? "alert-pct-error" : undefined}
            aria-invalid={errors.pctDrop ? true : undefined}
            className={`${inputClass} font-mono`}
          />
          <span className="font-mono text-ink2">%</span>
        </div>
        {errors.pctDrop && (
          <p id="alert-pct-error" role="alert" className="text-high">
            {errors.pctDrop}
          </p>
        )}
      </div>

      <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
        <legend className={`${labelClass} mb-1`}>Also alert me on</legend>
        <label className="flex items-center gap-3 text-ink">
          <input
            type="checkbox"
            checked={onNewLow}
            onChange={(event) => setOnNewLow(event.target.checked)}
            className="h-4 w-4 accent-ink"
          />
          New 90-day low
        </label>
        <label className="flex items-center gap-3 text-ink">
          <input
            type="checkbox"
            checked={onRestock}
            onChange={(event) => setOnRestock(event.target.checked)}
            className="h-4 w-4 accent-ink"
          />
          Back in stock
        </label>
      </fieldset>

      <p className="text-sm text-ink3">
        We&apos;ll email <span className="font-mono">{email}</span>.
      </p>

      {error && (
        <p role="alert" className="text-high">
          {error}
        </p>
      )}

      <div>
        <button type="submit" disabled={pending} className={primaryButtonClass}>
          {pending ? "Saving…" : "Start watching"}
        </button>
      </div>
    </form>
  );
}
