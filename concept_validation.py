import pandas as pd 
import numpy as np
import json 
import re 
import sys
from typing import Any, Iterator 
import httpx
from selectolax.parser import HTMLParser

URLS: list[tuple[str, str | None]] = [
    ("https://farmrio.com/products/rustic-flowers-winter-white-sleeveless-maxi-dress?variant=44352681902173&country=US&currency=USD&utm_medium=product_sync&utm_source=google&utm_content=sag_organic&utm_campaign=sag_organic&utm_id=22691767564&gad_source=1&gad_campaignid=22682102067&gbraid=0AAAAAC4GiQ_6Jqory_gos8887s2z-ljWi&gclid=Cj0KCQjwnIDUBhDrARIsAJDGwStufm1xGkXls0kiCRJvtTDNRd0YEh3FdTfEBKzjcfP34U-Ve2Fo1U0aAie-EALw_wcB", "298.00"),
    ("https://www.anthropologie.com/shop/farm-rio-x-anthropologie-sleeveless-mesh-midi-dress?color=627&inventoryCountry=US&countryCode=US&creative=&device=c&g_acctid=619-693-8226&g_adgroupid=&g_adid=&g_adtype=none&g_campaign=US+-+Shopping+-+PMAX+-+Apparel+-+Dresses+-+General&g_campaignid=19807768742&g_keyword=&g_keywordid=&g_network=x&g_type=shopping&matchtype=&network=x&utm_campaign=US+-+Shopping+-+PMAX+-+Apparel+-+Dresses+-+General&utm_content=&utm_kxconfid=vx6rd81ts&utm_medium=paid_search&utm_source=Google&utm_term=&gclsrc=aw.ds&gad_source=1&gad_campaignid=19800408132&gbraid=0AAAAADnwqi6XmdBNNA51Ff8hMfEwWVHzB&gclid=Cj0KCQjwnIDUBhDrARIsAJDGwSt6KtsShJLMfTn3kdhdiC2TL2wpOLono7utW2JkIjbevMB91uESoe4aAo5EEALw_wcB", "178.00"),
    ("https://shop.lululemon.com/p/women-shorts/Speed-Up-High-Rise-Short-4-Updated-MD/_/prod11900032?fp=1&color=62328", "59.00"),
    ("https://vuoriclothing.com/products/womens-daily-piped-bra-black?refSlotId=pdp-more-collection&objectId=41437918036071", "64.00"),
    ("https://www.bloomingdales.com/shop/product/maje-rishell-gold-jewelry-knit-midi-dress?ID=5855482#PRODUCT_DEPARTMENT/Dresses", "309.00"),
    ("https://www.tracksmith.com/products/w-meridian-speed-shorts?sku=WB716801BLK", "95.00")
]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
 
PRICE_KEYS = {
    "price", "lowprice", "highprice", "amount", "value",
    "currentprice", "saleprice", "listprice", "finalprice", "priceamount",
}
 
 
def walk(obj: Any) -> Iterator[tuple[str, Any]]:
    """Yield every (key, value) pair anywhere in a nested JSON structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)
 
 
def plausible_prices(obj: Any) -> list[str]:
    """Pull anything that looks like a price out of a JSON blob."""
    found = []
    for key, val in walk(obj):
        if key.lower().replace("_", "") not in PRICE_KEYS:
            continue
        if isinstance(val, (int, float)):
            found.append(f"{float(val):.2f}")
        elif isinstance(val, str) and re.fullmatch(r"[\d.,]+", val.strip()):
            try:
                found.append(f"{float(val.replace(',', '')):.2f}")
            except ValueError:
                pass
    return sorted(set(found), key=float)
 
 
def from_jsonld(tree: HTMLParser) -> list[str]:
    out = []
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            out += plausible_prices(json.loads(node.text()))
        except json.JSONDecodeError:
            continue
    return sorted(set(out), key=float)
 
 
def from_embedded_json(tree: HTMLParser) -> list[str]:
    """__NEXT_DATA__, __PRELOADED_STATE__, and friends."""
    out = []
    for node in tree.css("script"):
        sid = node.attributes.get("id", "") or ""
        text = node.text() or ""
        if sid == "__NEXT_DATA__":
            blob = text
        elif "__PRELOADED_STATE__" in text or "__INITIAL_STATE__" in text:
            m = re.search(r"=\s*(\{.*\})\s*;?\s*$", text.strip(), re.S)
            blob = m.group(1) if m else ""
        else:
            continue
        try:
            out += plausible_prices(json.loads(blob))
        except json.JSONDecodeError:
            continue
    return sorted(set(out), key=float)
 
 
def from_meta(tree: HTMLParser) -> list[str]:
    out = []
    for sel in ('meta[property="product:price:amount"]',
                'meta[itemprop="price"]',
                '[itemprop="price"]'):
        for node in tree.css(sel):
            v = node.attributes.get("content") or node.text() or ""
            v = re.sub(r"[^\d.]", "", v)
            if v:
                try:
                    out.append(f"{float(v):.2f}")
                except ValueError:
                    pass
    return sorted(set(out), key=float)
 
 
def verdict(status, jsonld, nextdata, meta, raw_hit, expected) -> str:
    if status != 200:
        return "BLOCKED — non-200, probably bot protection"
    if expected:
        if expected in jsonld:
            return "GOOD — JSON-LD has the right price"
        if expected in nextdata:
            return "GOOD — embedded JSON has the right price"
        if expected in meta:
            return "OK — only in meta tags, less stable"
        if raw_hit:
            return "CSS ONLY — price is in the HTML but not structured"
        return "NEEDS BROWSER — price not in raw HTML at all"
    if jsonld or nextdata:
        return "LIKELY GOOD — structured data present, verify the number"
    if meta:
        return "OK — meta tags only"
    return "UNKNOWN — pass an expected price to tell"
 
 
def check(url: str, expected: str | None) -> None:
    print(f"\n{'=' * 70}\n{url}")
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20) as c:
            r = c.get(url)
    except Exception as e:
        print(f"  request failed: {type(e).__name__}: {e}")
        print("  >>> BLOCKED or unreachable")
        return
 
    html = r.text
    tree = HTMLParser(html)
 
    jsonld = from_jsonld(tree)
    nextdata = from_embedded_json(tree)
    meta = from_meta(tree)
 
    # does the literal price string appear anywhere in the source?
    raw_hit = False
    if expected:
        bare = expected.replace(",", "")
        raw_hit = bare in html or expected in html
 
    print(f"  status        {r.status_code}   ({len(html):,} bytes)")
    print(f"  JSON-LD       {jsonld or '—'}")
    print(f"  embedded JSON {nextdata[:8] or '—'}")
    print(f"  meta/micro    {meta or '—'}")
    if expected:
        print(f"  expected      {expected}   in raw HTML: {'yes' if raw_hit else 'NO'}")
    print(f"  >>> {verdict(r.status_code, jsonld, nextdata, meta, raw_hit, expected)}")
 
    # keep the HTML — this becomes your first test fixture
    slug = re.sub(r"\W+", "-", url.split("//")[-1])[:60]
    with open(f"fixture-{slug}.html", "w", encoding="utf-8") as f:
        f.write(html)
 
 
if __name__ == "__main__":
    if URLS and URLS[0][0].startswith("https://www.example.com"):
        sys.exit("Put your own URLs in the URLS list first.")
    for url, expected in URLS:
        check(url, expected)
    print(f"\n{'=' * 70}\nSaved each page as fixture-*.html — those are your tests.")

