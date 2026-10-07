/**
 * Dashboard sort options. The sort itself runs in SQL (`.order()` in
 * queries.ts); this module only maps the `?sort=` param to a key.
 */

export type SortKey = "newest" | "oldest" | "name" | "best";

export const DEFAULT_SORT: SortKey = "newest";

export const SORT_OPTIONS: ReadonlyArray<{ key: SortKey; label: string }> = [
  { key: "newest", label: "Newest" },
  { key: "oldest", label: "Oldest" },
  { key: "name", label: "Name" },
  { key: "best", label: "Best deal" },
];

/** Unknown or missing values fall back to the default. */
export function parseSort(value: string | undefined): SortKey {
  const match = SORT_OPTIONS.find((option) => option.key === value);
  return match ? match.key : DEFAULT_SORT;
}
