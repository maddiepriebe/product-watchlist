import Link from "next/link";
import { DEFAULT_SORT, SORT_OPTIONS, type SortKey } from "@/lib/watchlist/sort";

/** Segmented sort links. Plain navigation: the server re-queries with ?sort=. */
export function SortControl({ current }: { current: SortKey }) {
  return (
    <nav aria-label="Sort watchlist" className="flex items-center gap-3 text-sm">
      <span className="text-ink3">Sort</span>
      <ul className="flex border border-rule" style={{ borderRadius: "var(--radius)" }}>
        {SORT_OPTIONS.map((option, i) => {
          const active = option.key === current;
          return (
            <li key={option.key} className={i > 0 ? "border-l border-rule" : ""}>
              <Link
                href={
                  option.key === DEFAULT_SORT
                    ? "/watchlist"
                    : `/watchlist?sort=${option.key}`
                }
                aria-current={active ? "true" : undefined}
                className={`block px-3 py-1.5 ${
                  active ? "bg-ink text-surface" : "text-ink2 hover:text-ink"
                }`}
              >
                {option.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
