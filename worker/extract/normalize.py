def normalize_url(url: str) -> tuple[str, str]:
    """Return (canonical_url, url_hash).

    Strips tracking params (utm_*, gad_*, gbraid, gclid, gclsrc, g_*,
    creative, device, network, matchtype) and any param with an empty value.
    Preserves variant, color, size, sku, country, currency.
    Sorts remaining params before hashing so order doesn't matter.
    """
    raise NotImplementedError
