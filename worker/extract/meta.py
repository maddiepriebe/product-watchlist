"""Title and image for display. Never prices.

JSON-LD Product name comes first because og:title and <title> usually carry
a " | Retailer" suffix; og:image comes first because it's the one image the
retailer picked for sharing.
"""

import html as htmllib
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from extract.findpath import load_blobs

_PRODUCT_TYPES = {"product", "productgroup"}
MAX_TITLE = 300


@dataclass(frozen=True)
class PageMeta:
    title: str | None
    image_url: str | None


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(htmllib.unescape(value).split())
    return text[:MAX_TITLE] or None


def _clean_url(value: Any, page_url: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    url = urljoin(page_url, value.strip())
    # The app serves over https; an http image would be blocked as mixed content.
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    if urlsplit(url).scheme != "https" or not urlsplit(url).netloc:
        return None
    return url


def _products(node: Any) -> Iterator[dict[str, Any]]:
    """Product/ProductGroup objects in a JSON-LD blob, including inside @graph."""
    if isinstance(node, list):
        for item in node:
            yield from _products(item)
    elif isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(isinstance(t, str) and t.lower() in _PRODUCT_TYPES for t in types):
            yield node
        if "@graph" in node:
            yield from _products(node["@graph"])


def _first_image(value: Any) -> Any:
    if isinstance(value, list):
        return _first_image(value[0]) if value else None
    if isinstance(value, dict):
        return value.get("url") or value.get("contentUrl")
    return value


def page_meta(html: str, page_url: str) -> PageMeta:
    tree = LexborHTMLParser(html)

    def meta(prop: str) -> str | None:
        node = tree.css_first(f'meta[property="{prop}"]') or tree.css_first(f'meta[name="{prop}"]')
        return node.attributes.get("content") if node is not None else None

    ld_title: str | None = None
    ld_image: str | None = None
    for blob in load_blobs(html):
        if blob.kind != "jsonld":
            continue
        for product in _products(blob.data):
            ld_title = ld_title or _clean_text(product.get("name"))
            ld_image = ld_image or _clean_url(_first_image(product.get("image")), page_url)

    title_node = tree.css_first("title")
    title = (
        ld_title
        or _clean_text(meta("og:title"))
        or _clean_text(title_node.text() if title_node is not None else None)
    )
    image = _clean_url(meta("og:image"), page_url) or ld_image
    return PageMeta(title=title, image_url=image)
