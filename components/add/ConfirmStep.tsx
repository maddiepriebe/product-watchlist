"use client";

import { useState } from "react";
import { formatMoney } from "@/lib/format";
import type { Detected, DetectedVariant } from "@/lib/add/types";
import {
  inputClass,
  labelClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "./ui";

export interface ConfirmChoice {
  /** null = watch every variant. */
  watchedVariantKeys: string[] | null;
  nickname: string;
}

function variantLabel(v: DetectedVariant): string {
  return [v.size, v.color].filter(Boolean).join(" · ") || "Default";
}

export function ConfirmStep({
  detected,
  pickVariants,
  askNickname,
  onConfirm,
  onReject,
  pending,
  error,
}: {
  detected: Detected;
  /** Show the variant picker (new watches with more than one variant). */
  pickVariants: boolean;
  askNickname: boolean;
  onConfirm: (choice: ConfirmChoice) => void;
  onReject: () => void;
  pending: boolean;
  error: string | null;
}) {
  const { variants } = detected;
  const showPicker = pickVariants && variants.length > 1;
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(variants.map((v) => v.variant_key)),
  );
  const [nickname, setNickname] = useState("");

  function toggle(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const nothingSelected = showPicker && selected.size === 0;

  function confirm() {
    const all = !showPicker || selected.size === variants.length;
    onConfirm({
      watchedVariantKeys: all
        ? null
        : variants.map((v) => v.variant_key).filter((key) => selected.has(key)),
      nickname: nickname.trim(),
    });
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex gap-4">
        {detected.image_url && (
          // Retailer images come from arbitrary hosts, so next/image's
          // remotePatterns allow-list can't cover them.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={detected.image_url}
            alt=""
            className="h-20 w-20 shrink-0 rounded-[2px] border border-rule object-cover"
          />
        )}
        <div className="min-w-0">
          <p className="font-medium text-ink">
            {detected.title ?? "Untitled product"}
          </p>
          <p className="mt-0.5 text-sm text-ink3">{detected.retailer}</p>
        </div>
      </div>

      <fieldset className="m-0 min-w-0 border-0 p-0">
        <legend className={`${labelClass} mb-2`}>
          {showPicker
            ? "Choose the options to watch"
            : variants.length > 1
              ? "Prices found"
              : "Price found"}
        </legend>
        <ul className="border-y border-rule">
          {variants.map((v) => (
            <li
              key={v.variant_key}
              className="flex items-center gap-3 border-b border-rule py-2 last:border-b-0"
            >
              {showPicker && (
                <input
                  id={`variant-${v.variant_key}`}
                  type="checkbox"
                  checked={selected.has(v.variant_key)}
                  onChange={() => toggle(v.variant_key)}
                  className="h-4 w-4 accent-ink"
                />
              )}
              <label
                htmlFor={showPicker ? `variant-${v.variant_key}` : undefined}
                className="min-w-0 flex-1 truncate text-ink"
              >
                {variantLabel(v)}
              </label>
              <span
                className={`text-sm ${v.in_stock ? "text-ink3" : "text-high"}`}
              >
                {v.in_stock ? "In stock" : "Sold out"}
              </span>
              <span className="w-24 text-right font-mono text-ink">
                {formatMoney(v.price_cents, v.currency)}
              </span>
            </li>
          ))}
        </ul>
        {nothingSelected && (
          <p role="alert" className="mt-2 text-high">
            Choose at least one option to watch.
          </p>
        )}
      </fieldset>

      {askNickname && (
        <div className="flex flex-col gap-2">
          <label htmlFor="nickname" className={labelClass}>
            Nickname (optional)
          </label>
          <input
            id="nickname"
            type="text"
            maxLength={120}
            value={nickname}
            onChange={(event) => setNickname(event.target.value)}
            placeholder={detected.title ?? "What you call it"}
            className={inputClass}
          />
        </div>
      )}

      {error && (
        <p role="alert" className="text-high">
          {error}
        </p>
      )}

      <div className="flex flex-col gap-3 sm:flex-row">
        <button
          type="button"
          onClick={confirm}
          disabled={pending || nothingSelected}
          className={primaryButtonClass}
        >
          Yes, that&apos;s the price I see
        </button>
        <button
          type="button"
          onClick={onReject}
          disabled={pending}
          className={secondaryButtonClass}
        >
          That&apos;s not right
        </button>
      </div>
    </div>
  );
}
