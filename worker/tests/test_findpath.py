import json
from pathlib import Path

import pytest

from extract.findpath import find_paths, load_blobs, parse_price_text

FIXTURES = Path(__file__).parent / "fixtures"
FARMRIO = "fixture-farmrio-com-products-rustic-flowers-winter-white-sleeveless-.html"
VUORI = "fixture-vuoriclothing-com-products-womens-daily-piped-bra-black-refS.html"
TRACKSMITH = "fixture-www-tracksmith-com-products-w-meridian-speed-shorts-sku-WB71.html"
ANTHRO = "fixture-www-anthropologie-com-shop-farm-rio-x-anthropologie-sleevele.html"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def page(*, jsonld: list[object] = (), nextdata: object | None = None) -> str:
    parts = [
        f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in jsonld
    ]
    if nextdata is not None:
        parts.append(f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(nextdata)}</script>')
    return "<html><head>" + "".join(parts) + "</head><body></body></html>"


@pytest.mark.parametrize(
    "text, cents",
    [
        ("$298.00", 29800),
        ("298", 29800),
        ("298.00", 29800),
        ("$1,298.50", 129850),
        ("1,298", 129800),
        ("  $ 64 ", 6400),
        ("US$95.00", 9500),
        ("95.00 USD", 9500),
        ("$12.5", 1250),
        ("£40", 4000),
        ("298,00", None),        # comma decimal: locale-ambiguous
        ("1.298,50", None),
        ("$248 $298", None),     # two numbers
        ("Was $298 now $248", None),
        ("$298.005", None),      # sub-cent
        ("12,34,567", None),
        ("$", None),
        ("", None),
        ("free", None),
        ("0", None),
        ("$0.00", None),
        ("-5", None),
        ("1e3", None),
    ],
)
def test_parse_price_text(text: str, cents: int | None) -> None:
    assert parse_price_text(text) == cents


def test_parse_price_text_returns_int_not_float() -> None:
    assert type(parse_price_text("$19.99")) is int
    assert parse_price_text("$19.99") == 1999   # float math would give 1998.99…


def test_farmrio_price_found_in_jsonld_offers() -> None:
    cands = find_paths(fixture(FARMRIO), 29800)
    assert cands, "expected a match"
    best = cands[0]
    assert (best.blob, best.block, best.unit) == ("jsonld", 1, "major")
    assert best.path == ("offers", 0, "price")


def test_tracksmith_price_found_in_jsonld_string_value() -> None:
    # Tracksmith's offer price is the string "95.0".
    cands = find_paths(fixture(TRACKSMITH), 9500)
    assert cands[0].blob == "jsonld"
    assert cands[0].path == ("offers", "price")
    assert cands[0].config() == {
        "learned": True, "blob": "jsonld", "block": 0,
        "path": ["offers", "price"], "unit": "major",
    }


def test_anthropologie_price_found_in_third_jsonld_block() -> None:
    cands = find_paths(fixture(ANTHRO), 17800)
    assert (cands[0].blob, cands[0].block, cands[0].path) == ("jsonld", 2, ("offers", "price"))


def test_vuori_price_found_in_next_data() -> None:
    cands = find_paths(fixture(VUORI), 6400)
    nextdata = [c for c in cands if c.blob == "nextdata"]
    assert ("props", "pageProps", "pdpPageProps", "variants", 0, "price") in [c.path for c in nextdata]
    assert all(c.block is None for c in nextdata)
    # JSON-LD still ranks first when both have it.
    assert cands[0].blob == "jsonld"
    assert nextdata[0].config()["blob"] == "nextdata"
    assert "block" not in nextdata[0].config()


def test_vuori_selling_price_ranks_before_compare_at_price() -> None:
    nextdata = [c for c in find_paths(fixture(VUORI), 6400) if c.blob == "nextdata"]
    keys = [c.path[-1] for c in nextdata]
    assert keys.index("compareAtPrice") > keys.index("price")
    assert keys[-1] == "compareAtPrice"


def test_ordering_is_deterministic() -> None:
    html = fixture(VUORI)
    assert find_paths(html, 6400) == find_paths(html, 6400)


def test_wrong_price_finds_nothing() -> None:
    assert find_paths(fixture(FARMRIO), 29700) == []


def test_never_selects_size_values() -> None:
    product = {
        "@type": "Product",
        "size": "8",
        "options": [{"name": "Size", "values": ["8", "10"]}],
        "hasVariant": [{"size": 8, "sku": "800", "position": 8}],
        "offers": {"price": "8.00"},
    }
    cands = find_paths(page(jsonld=[product]), 800)
    assert [c.path for c in cands] == [("offers", "price")]


def test_only_size_matches_means_no_candidate() -> None:
    product = {"@type": "Product", "size": "8", "offers": {"price": "9.00"}}
    assert find_paths(page(jsonld=[product]), 800) == []


def test_minor_units() -> None:
    html = page(nextdata={"props": {"product": {"priceCents": 29800, "price": "298.00"}}})
    cands = find_paths(html, 29800)
    by_unit = {c.unit: c.path for c in cands}
    assert by_unit["major"] == ("props", "product", "price")
    assert by_unit["minor"] == ("props", "product", "priceCents")


def test_decimal_minor_lookalike_is_not_minor() -> None:
    html = page(nextdata={"p": {"price": "29800.00"}})
    assert find_paths(html, 29800) == []


def test_jsonld_block_index_counts_broken_blocks() -> None:
    html = (
        '<script type="application/ld+json">{not json</script>'
        '<script type="application/ld+json">{"offers": {"price": 10}}</script>'
    )
    blobs = load_blobs(html)
    assert [b.block for b in blobs] == [1]
    assert find_paths(html, 1000)[0].block == 1


def test_booleans_are_not_numbers() -> None:
    assert find_paths(page(jsonld=[{"price": True}]), 100) == []
