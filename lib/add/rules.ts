import { parseMoneyToCents, parsePercent } from "@/lib/money";

/** What the alert form holds: raw strings plus the two checkboxes. */
export interface AlertRulesInput {
  below: string;
  pctDrop: string;
  onNewLow: boolean;
  onRestock: boolean;
}

/** Validated rules in DB shape (null = rule off). */
export interface AlertRules {
  alertBelowCents: number | null;
  alertPctDrop: number | null;
  alertOnNewLow: boolean;
  alertOnRestock: boolean;
}

export type AlertRulesResult =
  | { ok: true; rules: AlertRules }
  | { ok: false; errors: { below?: string; pctDrop?: string } };

/**
 * "15" → 15, "12.5%" → 12.5. Must be above 0 and at most 99.99, with at most
 * two decimals (the column is numeric(5,2)). Percent is not money, so a number
 * is the right type; it is only ever built from a validated digit string.
 */
/** Shared by the form (inline errors) and the save action (re-validation). */
export function parseAlertRules(input: AlertRulesInput): AlertRulesResult {
  const errors: { below?: string; pctDrop?: string } = {};

  let alertBelowCents: number | null = null;
  if (input.below.trim() !== "") {
    const cents = parseMoneyToCents(input.below);
    if (cents === null || cents === 0) {
      errors.below = "Enter a price above $0, like $249.99 or 250.";
    } else {
      alertBelowCents = cents;
    }
  }

  let alertPctDrop: number | null = null;
  if (input.pctDrop.trim() !== "") {
    const pct = parsePercent(input.pctDrop);
    if (pct === null) {
      errors.pctDrop = "Enter a percent above 0 and up to 99.99, like 15.";
    } else {
      alertPctDrop = pct;
    }
  }

  if (errors.below || errors.pctDrop) return { ok: false, errors };
  return {
    ok: true,
    rules: {
      alertBelowCents,
      alertPctDrop,
      alertOnNewLow: input.onNewLow,
      alertOnRestock: input.onRestock,
    },
  };
}
