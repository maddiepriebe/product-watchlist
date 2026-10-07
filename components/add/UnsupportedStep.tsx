"use client";

import { linkButtonClass, primaryButtonClass } from "./ui";

/** We can't read this page. Be plain about it and let the user decide. */
export function UnsupportedStep({
  message,
  retailer,
  title,
  onKeep,
  onCancel,
  pending,
  error,
}: {
  message: string;
  retailer: string;
  title: string | null;
  onKeep: () => void;
  onCancel: () => void;
  pending: boolean;
  error: string | null;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="font-medium text-ink">{title ?? retailer}</p>
        {title && <p className="mt-0.5 text-sm text-ink3">{retailer}</p>}
      </div>
      <p className="text-ink">{message}</p>
      <p className="text-ink2">
        We can keep this link on your watchlist, but it won&apos;t show prices
        or send alerts until we can read this retailer.
      </p>
      {error && (
        <p role="alert" className="text-high">
          {error}
        </p>
      )}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-5">
        <button
          type="button"
          onClick={onKeep}
          disabled={pending}
          className={primaryButtonClass}
        >
          Keep watching anyway
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={pending}
          className={linkButtonClass}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
