/** Display helpers for variant keys ("size|color", lowercase; "" = no variants). */

const LETTER_SIZE = /^x{0,3}[sml]$|^\d+xl$/i;

/** "m" -> "M", "xl" -> "XL"; "one size" and "32" stay as given. */
function formatSize(size: string): string {
  return LETTER_SIZE.test(size) ? size.toUpperCase() : size;
}

/** "m|black" -> "M · black"; "|black" -> "black"; "" -> "Default". */
export function formatVariantKey(key: string): string {
  const [size = "", color = ""] = key.split("|");
  const parts = [formatSize(size.trim()), color.trim()];
  return parts.filter(Boolean).join(" · ") || "Default";
}
