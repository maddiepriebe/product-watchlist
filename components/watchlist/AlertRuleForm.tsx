"use client";

import { useActionState } from "react";
import { updateAlertRules } from "@/app/(app)/watchlist/actions";
import type { RuleFormState } from "@/lib/watchlist/types";

type AlertRuleFormProps = {
  watchId: string;
  /** Pre-filled values, already formatted ("250.00", "10"). Empty = rule off. */
  belowDefault: string;
  pctDefault: string;
  onNewLow: boolean;
  onRestock: boolean;
};

const INITIAL: RuleFormState = { status: "idle" };

const inputClass =
  "w-full border border-rule bg-ground px-3 py-2 font-mono text-sm text-ink outline-none focus:border-ink aria-[invalid=true]:border-high";

export function AlertRuleForm({
  watchId,
  belowDefault,
  pctDefault,
  onNewLow,
  onRestock,
}: AlertRuleFormProps) {
  const [state, formAction, pending] = useActionState(
    updateAlertRules,
    INITIAL,
  );
  const errors = state.fieldErrors ?? {};

  return (
    <form action={formAction} className="space-y-4">
      <input type="hidden" name="watch_id" value={watchId} />

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor={`below-${watchId}`} className="text-sm text-ink3">
            Alert at or below
          </label>
          <div className="mt-1">
            <input
              id={`below-${watchId}`}
              name="alert_below"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              placeholder="$250.00"
              defaultValue={belowDefault}
              aria-invalid={errors.below ? true : undefined}
              aria-describedby={errors.below ? `below-err-${watchId}` : undefined}
              className={inputClass}
              style={{ borderRadius: "var(--radius)" }}
            />
          </div>
          {errors.below && (
            <p id={`below-err-${watchId}`} className="mt-1 text-sm text-high">
              {errors.below}
            </p>
          )}
        </div>

        <div>
          <label htmlFor={`pct-${watchId}`} className="text-sm text-ink3">
            Alert on drop vs 30-day median (%)
          </label>
          <div className="mt-1">
            <input
              id={`pct-${watchId}`}
              name="alert_pct_drop"
              type="text"
              inputMode="decimal"
              autoComplete="off"
              placeholder="10"
              defaultValue={pctDefault}
              aria-invalid={errors.pct ? true : undefined}
              aria-describedby={errors.pct ? `pct-err-${watchId}` : undefined}
              className={inputClass}
              style={{ borderRadius: "var(--radius)" }}
            />
          </div>
          {errors.pct && (
            <p id={`pct-err-${watchId}`} className="mt-1 text-sm text-high">
              {errors.pct}
            </p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-ink">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            name="alert_on_new_low"
            defaultChecked={onNewLow}
            className="size-4 accent-ink"
          />
          New 90-day low
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            name="alert_on_restock"
            defaultChecked={onRestock}
            className="size-4 accent-ink"
          />
          Back in stock
        </label>
      </div>

      <div className="flex items-center gap-4">
        <button
          type="submit"
          disabled={pending}
          className="bg-ink px-3 py-2 text-sm text-surface disabled:opacity-60"
          style={{ borderRadius: "var(--radius)" }}
        >
          {pending ? "Saving…" : "Save alerts"}
        </button>
        <p
          role="status"
          className={`text-sm ${state.status === "error" ? "text-high" : "text-ink2"}`}
        >
          {state.message}
        </p>
      </div>
    </form>
  );
}
