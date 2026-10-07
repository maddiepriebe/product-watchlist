"""Which variant does the pasted URL point at?

Product URLs often pin one variant: Farm Rio `?variant=44352681902173`,
Tracksmith `?sku=WB716801BLK`. When the page's structured data names that
variant, we can tell which offer to learn a price path from and which
"size|color" key it has, so a watch can be limited to that variant.

Only explicit matches count. Query values are compared for exact equality
with ids the page itself states; nothing is inferred from names, positions or
image URLs. If zero offers match, or more than one, the answer is None and the
caller falls back to treating the page as unpinned.

Sources, all fixture-grounded:
- JSON-LD: every Offer under a node with "offers". Its identity is the query
  params of its own `url` (`variant`, `objectId`, `sku`, `color`, `size`) and
  its `sku` / `gtin*` / `productID`. The parent product's ids and its
  size/color count too, but only when the parent has exactly one offer.
- __NEXT_DATA__: only `props.pageProps.pdpPageProps.variants[*]` (Vuori),
  whose `id` (a Shopify gid; its numeric tail is the `objectId`), `sku` and
  `selectedOptions` (Size, Color) are explicit.

Anthropologie's `?color=627` is a retailer colour code that appears in no
structured data (only in image URLs), so it matches nothing and yields None.
"""

from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlsplit

from extract.findpath import Blob, Location, PathKey, load_blobs
from extract.variantkey import variant_key

# URL params that can pick a variant. Anything else (utm_*, country, …) is ignored.
SELECTOR_PARAMS = ("variant", "objectid", "sku", "color", "size")
_ID_FIELDS = ("sku", "productID", "gtin", "gtin8", "gtin12", "gtin13", "gtin14")
NEXT_VARIANTS_PATH: tuple[PathKey, ...] = ("props", "pageProps", "pdpPageProps", "variants")


@dataclass(frozen=True)
class PinnedVariant:
    """The variant the URL points at, and where the page's JSON describes it."""

    locations: tuple[Location, ...]   # one per blob that matched (1 or 2)
    size: str | None
    color: str | None

    @property
    def key(self) -> str:
        return variant_key(self.size, self.color)


@dataclass(frozen=True)
class _Node:
    """One variant-like object in the page's JSON, reduced to what a URL can name."""

    location: Location
    ids: frozenset[str]                  # sku / gtin / productID values
    params: dict[str, frozenset[str]]    # lowercase param name -> values
    size: str | None
    color: str | None


def _text(value: Any) -> str | None:
    """A JSON leaf as a trimmed string; numbers count, bools and empties don't."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        s = str(value).strip()
        return s or None
    return None


def _name(value: Any) -> str | None:
    """schema.org size/color: a string, or a thing with a `name`."""
    if isinstance(value, dict):
        value = value.get("name")
    return _text(value) if isinstance(value, str) else None


def url_selectors(url: str) -> dict[str, str] | None:
    """The variant-picking query params of `url`, or None if there are none or they conflict."""
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=False)
    except ValueError:
        return None
    found: dict[str, str] = {}
    for k, v in pairs:
        name = k.strip().lower()
        v = v.strip()
        if name not in SELECTOR_PARAMS or not v:
            continue
        if found.setdefault(name, v) != v:
            return None   # ?variant=1&variant=2 names no single variant
    return found or None


def _query_params(url: Any) -> dict[str, frozenset[str]]:
    if not isinstance(url, str):
        return {}
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=False)
    except ValueError:
        return {}
    out: dict[str, set[str]] = {}
    for k, v in pairs:
        if v.strip():
            out.setdefault(k.strip().lower(), set()).add(v.strip())
    return {k: frozenset(v) for k, v in out.items()}


def _ids(node: dict[str, Any]) -> set[str]:
    return {s for f in _ID_FIELDS if (s := _text(node.get(f)))}


# ------------------------------------------------------------- JSON-LD

def _jsonld_nodes(blob: Blob) -> Iterator[_Node]:
    def visit(obj: Any, path: tuple[PathKey, ...]) -> Iterator[_Node]:
        if isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from visit(v, path + (i,))
            return
        if not isinstance(obj, dict):
            return
        offers = obj.get("offers")
        if isinstance(offers, dict):
            offer_list: list[tuple[tuple[PathKey, ...], Any]] = [(path + ("offers",), offers)]
        elif isinstance(offers, list):
            offer_list = [(path + ("offers", i), o) for i, o in enumerate(offers)]
        else:
            offer_list = []
        offer_list = [(p, o) for p, o in offer_list if isinstance(o, dict) and "offers" not in o]
        sole = len(offer_list) == 1   # the product's own ids/size/color describe its only offer
        for p, offer in offer_list:
            item = offer.get("itemOffered")
            item = item if isinstance(item, dict) else {}
            ids = _ids(offer) | (_ids(item) if item else set())
            size = _name(offer.get("size")) or _name(item.get("size"))
            color = _name(offer.get("color")) or _name(item.get("color"))
            if sole:
                ids |= _ids(obj)
                size = size or _name(obj.get("size"))
                color = color or _name(obj.get("color"))
            yield _Node(Location("jsonld", blob.block, p), frozenset(ids),
                        _query_params(offer.get("url")), size, color)
        for k, v in obj.items():
            yield from visit(v, path + (k,))

    yield from visit(blob.data, ())


# ---------------------------------------------------------- __NEXT_DATA__

def _nextdata_nodes(blob: Blob) -> Iterator[_Node]:
    node: Any = blob.data
    for k in NEXT_VARIANTS_PATH:
        if not isinstance(node, dict) or k not in node:
            return
        node = node[k]
    if not isinstance(node, list):
        return
    for i, v in enumerate(node):
        if not isinstance(v, dict):
            continue
        vid = _text(v.get("id"))
        ids = {s for s in (_text(v.get("sku")),) if s}
        params: dict[str, frozenset[str]] = {}
        if vid:
            tail = vid.rsplit("/", 1)[-1]
            params = {"variant": frozenset({vid, tail}), "objectid": frozenset({vid, tail})}
        size = color = None
        opts = v.get("selectedOptions")
        for o in opts if isinstance(opts, list) else []:
            if not isinstance(o, dict):
                continue
            name = _text(o.get("name"))
            value = _text(o.get("value"))
            if name and name.lower() == "size":
                size = value
            elif name and name.lower() == "color":
                color = value
        yield _Node(Location("nextdata", None, NEXT_VARIANTS_PATH + (i,)),
                    frozenset(ids), params, size, color)


# --------------------------------------------------------------- matching

def _norm(s: str | None) -> str:
    return " ".join((s or "").lower().split())


def _matches(node: _Node, selectors: dict[str, str]) -> bool:
    """Every selector in the URL must be satisfied by this node."""
    for name, value in selectors.items():
        if name == "sku":
            ok = value in node.ids or value in node.params.get("sku", ())
        elif name in ("variant", "objectid"):
            ok = value in node.params.get(name, ())
        else:   # color / size: the node's own field or its url param, ignoring case
            field = node.color if name == "color" else node.size
            ok = _norm(value) == _norm(field) or any(
                _norm(value) == _norm(p) for p in node.params.get(name, ()))
        if not ok:
            return False
    return True


def find_pinned_variant(html: str, url: str) -> PinnedVariant | None:
    """The offer the pasted URL points at, or None unless exactly one matches."""
    selectors = url_selectors(url)
    if selectors is None:
        return None

    jsonld: list[_Node] = []
    nextdata: list[_Node] = []
    for blob in load_blobs(html):
        if blob.kind == "jsonld":
            jsonld += [n for n in _jsonld_nodes(blob) if _matches(n, selectors)]
        else:
            nextdata += [n for n in _nextdata_nodes(blob) if _matches(n, selectors)]
    if len(jsonld) > 1 or len(nextdata) > 1:
        return None
    nodes = jsonld + nextdata
    if not nodes:
        return None

    # The same variant seen in two blobs must agree on its key.
    keys = {k for n in nodes if (k := variant_key(n.size, n.color))}
    if len(keys) > 1:
        return None
    best = next((n for n in nodes if variant_key(n.size, n.color)), nodes[0])
    return PinnedVariant(tuple(n.location for n in nodes), best.size, best.color)
