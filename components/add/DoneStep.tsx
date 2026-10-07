"use client";

import Link from "next/link";
import {
  primaryButtonClass,
  secondaryButtonClass,
} from "./ui";

/** Shown after a successful save, in place of an immediate redirect. */
export function DoneStep({
  watchId,
  linked,
  readable,
  onLinkAnother,
}: {
  watchId: string;
  /** True when a source was added to an existing watch. */
  linked: boolean;
  /** False when the page couldn't be read, so no price check will follow. */
  readable: boolean;
  onLinkAnother: () => void;
}) {
  const heading = linked ? "Linked." : "Saved.";
  const detail = readable
    ? linked
      ? "We'll check this site's price within a few minutes."
      : "We'll check the price within a few minutes."
    : "We'll keep the link, but we can't show prices from this store yet.";

  return (
    <div className="flex flex-col gap-4" role="status">
      <p className="text-ink">
        <span className="font-medium">{heading}</span> {detail}
      </p>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-5">
        {linked ? (
          <button
            type="button"
            onClick={onLinkAnother}
            className={primaryButtonClass}
          >
            Link another site
          </button>
        ) : (
          <Link href={`/add?watch=${watchId}`} className={primaryButtonClass}>
            Add another site for this item
          </Link>
        )}
        <Link
          href="/watchlist"
          className={secondaryButtonClass}
        >
          Go to your watchlist
        </Link>
      </div>
    </div>
  );
}
