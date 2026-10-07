"""Read a price through a learned extractor_config (see docs/worker-api.md).

The path either resolves to an exact number or the check fails. There is no
fallback search: if the retailer reshapes its JSON, the source starts
failing and the user re-teaches it, rather than us guessing a new path.

A config taught from a URL that pinned one variant also carries that
variant's `variant_key` (plus `size` and `color`), and resolve() reports it.
Configs without one, which is every config taught before pinning existed,
report no key (the scheduler stores that as "").
"""

import re
from typing import Any, Mapping

from extract.base import Extracted
from extract.findpath import cents_from, load_blobs
from extract.variantkey import is_well_formed

# schema.org availability values that mean "you can't buy it now".
# Anything else (InStock, LimitedAvailability, OnlineOnly, …) counts as in stock.
_OUT_OF_STOCK = {"outofstock", "soldout", "discontinued", "preorder", "presale", "backorder"}
_CURRENCY_KEYS = ("priceCurrency", "currency", "currencyCode")


def _valid(config: Mapping[str, Any]) -> bool:
    if config.get("learned") is not True:
        return False
    if config.get("blob") not in ("jsonld", "nextdata"):
        return False
    if config.get("unit") not in ("major", "minor"):
        return False
    path = config.get("path")
    if not isinstance(path, list) or not path:
        return False
    if not all(isinstance(k, str) or (isinstance(k, int) and not isinstance(k, bool)) for k in path):
        return False
    if config["blob"] == "jsonld":
        block = config.get("block")
        return isinstance(block, int) and not isinstance(block, bool) and block >= 0
    return True


def config_variant_key(config: Mapping[str, Any]) -> str | None:
    """The pinned variant's key, or None for configs that don't carry a usable one."""
    key = config.get("variant_key")
    return key if isinstance(key, str) and key and is_well_formed(key) else None


def _follow(data: Any, path: list[str | int]) -> tuple[Any, Any] | None:
    """(parent, value) at path, or None if any step is missing."""
    parent = None
    node = data
    for key in path:
        parent = node
        if isinstance(key, int) and isinstance(node, list):
            if not 0 <= key < len(node):
                return None
            node = node[key]
        elif isinstance(key, str) and isinstance(node, dict):
            if key not in node:
                return None
            node = node[key]
        else:
            return None
    return parent, node


def availability_in_stock(value: Any) -> bool | None:
    """schema.org availability ("https://schema.org/InStock") -> bool, or None if unrecognised."""
    if not isinstance(value, str) or not value.strip():
        return None
    name = re.split(r"[/#]", value.strip())[-1].lower()
    return name not in _OUT_OF_STOCK


def _currency(parent: Any) -> str:
    if isinstance(parent, dict):
        for k in _CURRENCY_KEYS:
            v = parent.get(k)
            if isinstance(v, str) and re.fullmatch(r"[A-Za-z]{3}", v.strip()):
                return v.strip().upper()
    return "USD"


def resolve(html: str, config: Mapping[str, Any]) -> list[Extracted]:
    """One Extracted (variant_key from the config, else None) if the path still holds an exact price, else []."""
    if not _valid(config):
        return []
    blob_kind = config["blob"]
    block = config.get("block") if blob_kind == "jsonld" else None
    blob = next(
        (b for b in load_blobs(html) if b.kind == blob_kind and b.block == block), None
    )
    if blob is None:
        return []
    found = _follow(blob.data, config["path"])
    if found is None:
        return []
    parent, value = found
    cents = cents_from(value, config["unit"])
    if cents is None or cents <= 0:
        return []

    in_stock = True
    if isinstance(parent, dict):
        avail = availability_in_stock(parent.get("availability"))
        if avail is not None:
            in_stock = avail

    return [
        Extracted(
            price_cents=cents,
            currency=_currency(parent),
            in_stock=in_stock,
            variant_key=config_variant_key(config),
            strategy=f"learned:{blob_kind}",
        )
    ]
