from dataclasses import dataclass


@dataclass
class Extracted:
    price_cents: int
    currency: str
    in_stock: bool
    variant_key: str | None   # normalized "size|color"
    strategy: str


def extract(html: str, url: str) -> list[Extracted]:
    """Return one Extracted per variant found, or [] on failure.

    NEVER return a guess. No price is recoverable; a wrong price is not.
    Dispatches to a per-domain extractor registry, falling back to
    generic JSON-LD. Each extractor uses explicit JSON paths — no
    key-name heuristics.
    """
    raise NotImplementedError
