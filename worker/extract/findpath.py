"""The "teach the extractor" search.

When automatic extraction can't find a price, the user types the price they
see. We search the page's structured data for a value exactly equal to it and
remember that JSON path; later checks read the same path (learned.py). The
user's text is never saved as a price, only used to locate one.

JSON is parsed with parse_float=Decimal so no float ever touches a price.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator, Literal, Sequence

from selectolax.lexbor import LexborHTMLParser

BlobKind = Literal["jsonld", "nextdata"]
Unit = Literal["major", "minor"]
PathKey = str | int


@dataclass(frozen=True)
class Blob:
    kind: BlobKind
    block: int | None   # index among all JSON-LD <script>s (jsonld only)
    data: Any


@dataclass(frozen=True)
class Location:
    """A spot in a page's JSON: which blob, which JSON-LD block, which path."""

    blob: BlobKind
    block: int | None
    path: tuple[PathKey, ...]


@dataclass(frozen=True)
class Candidate:
    blob: BlobKind
    block: int | None
    path: tuple[PathKey, ...]
    unit: Unit

    def within(self, loc: Location) -> bool:
        """True if this path lies at or below `loc` (same blob, same block)."""
        return (
            self.blob == loc.blob
            and self.block == loc.block
            and self.path[: len(loc.path)] == loc.path
        )

    def config(self) -> dict[str, Any]:
        """The extractor_config shape in docs/worker-api.md."""
        cfg: dict[str, Any] = {"learned": True, "blob": self.blob}
        if self.blob == "jsonld":
            cfg["block"] = self.block
        cfg["path"] = list(self.path)
        cfg["unit"] = self.unit
        return cfg


# ------------------------------------------------------------------
# page -> JSON blobs
# ------------------------------------------------------------------

def parse_json(text: str) -> Any:
    return json.loads(text, parse_float=Decimal, strict=False)


def load_blobs(html: str) -> list[Blob]:
    """Every parseable JSON-LD block, then __NEXT_DATA__ if present.

    JSON-LD block numbers count unparseable blocks too, so a learned
    `block` index stays stable if a sibling block is broken one day.
    """
    tree = LexborHTMLParser(html)
    blobs: list[Blob] = []
    for i, node in enumerate(tree.css('script[type="application/ld+json"]')):
        try:
            blobs.append(Blob("jsonld", i, parse_json(node.text() or "")))
        except ValueError:
            continue
    nd = tree.css_first("script#__NEXT_DATA__")
    if nd is not None:
        try:
            blobs.append(Blob("nextdata", None, parse_json(nd.text() or "")))
        except ValueError:
            pass
    return blobs


# ------------------------------------------------------------------
# price text -> cents
# ------------------------------------------------------------------

# One number, US formatting: plain digits or comma-grouped thousands, with an
# optional 1–2 digit decimal part. "298,00" and "1.298,50" don't match:
# they're ambiguous without knowing the locale, so we ask again.
_NUMBER = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?")
_CURRENCY_PREFIX = re.compile(r"^(?:US\$|USD|\$|£|€)\s*", re.I)
_CURRENCY_SUFFIX = re.compile(r"\s*(?:USD)$", re.I)


def parse_price_text(text: str) -> int | None:
    """"$1,298.50" -> 129850, "298" -> 29800; anything ambiguous -> None."""
    s = text.strip()
    s = _CURRENCY_PREFIX.sub("", s, count=1)
    s = _CURRENCY_SUFFIX.sub("", s, count=1)
    if not _NUMBER.fullmatch(s):
        return None
    cents = Decimal(s.replace(",", "")) * 100
    if cents != cents.to_integral_value() or cents <= 0:
        return None
    return int(cents)


def to_decimal(value: Any) -> Decimal | None:
    """A JSON leaf as an exact number: ints, Decimals, or plain numeric strings."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    if isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            return None
    return None


def cents_from(value: Any, unit: Unit) -> int | None:
    """Exact conversion of a JSON leaf to cents, or None if it isn't exact."""
    d = to_decimal(value)
    if d is None:
        return None
    cents = d * 100 if unit == "major" else d
    if cents != cents.to_integral_value():
        return None
    return int(cents)


# ------------------------------------------------------------------
# the search
# ------------------------------------------------------------------

def walk(obj: Any, path: tuple[PathKey, ...] = ()) -> Iterator[tuple[tuple[PathKey, ...], Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + (i,))
    else:
        yield path, obj


def leaf_key(path: tuple[PathKey, ...]) -> str:
    """The nearest dict key: "price" for (..., "price") and (..., "prices", 0)."""
    for k in reversed(path):
        if isinstance(k, str):
            return k.lower()
    return ""


def is_price_key(key: str) -> bool:
    # Only keys that name a price may match. A $8 item must never learn a
    # path to {"size": "8"}, and option/variant values are full of numbers.
    return "price" in key or "amount" in key


# Keys that usually hold a reference price rather than the selling price. They
# still count (a page may only expose listPrice) but rank last: when an item
# goes on sale, a path to compareAtPrice would keep reporting the old price.
_REFERENCE_KEY = re.compile(r"compare|list|regular|original|was|msrp|high|max")


def find_paths(
    html: str, target_cents: int, prefer: Sequence[Location] = ()
) -> list[Candidate]:
    """Every JSON path whose value equals target_cents, best first.

    Order: paths inside a `prefer` location (the offer the pasted URL points
    at, see urlvariant.py) before everything else; then JSON-LD offers paths, then other JSON-LD, then __NEXT_DATA__;
    within that, selling-price keys before reference-price keys, shorter
    paths first, a key literally named "price" first, then document order.
    """
    target = Decimal(target_cents)
    ranked: list[tuple[tuple[int, int, int, int, int, int, int], Candidate]] = []
    order = 0
    for blob in load_blobs(html):
        for path, value in walk(blob.data):
            order += 1
            key = leaf_key(path)
            if not is_price_key(key):
                continue
            d = to_decimal(value)
            if d is None:
                continue
            units: list[Unit] = []
            if d * 100 == target:
                units.append("major")
            if d == target and d == d.to_integral_value() and "." not in str(value):
                units.append("minor")
            for unit in units:
                c = Candidate(blob.kind, blob.block, path, unit)
                rank = (
                    0 if any(c.within(loc) for loc in prefer) else 1,
                    0 if blob.kind == "jsonld" and "offers" in path else 1,
                    0 if blob.kind == "jsonld" else 1,
                    1 if _REFERENCE_KEY.search(key) else 0,
                    len(path),
                    0 if key == "price" else 1,
                    order,
                )
                ranked.append((rank, c))
    ranked.sort(key=lambda rc: rc[0])
    return [c for _, c in ranked]
