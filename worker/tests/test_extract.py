"""Tests for extract.base.extract(html, url) -> list[Extracted].

Ground truth, established by inspecting the saved fixtures:

* farmrio      JSON-LD Product with 6 Offers (one per size), all 298.00 USD, all InStock.
               The URL's ?variant=44352681902173 corresponds to the offer with sku
               196198770105; every offer has the same price, so per-variant filtering
               cannot change the price.
* anthropologie JSON-LD Product, single Offer, 178 USD, InStock. ?color=627 is not
               represented in the page's structured data.
* vuori        Next.js. JSON-LD ProductGroup + 7 hasVariant Products (XXS..XXL, Black),
               every offer 64 USD. XXS, S, XXL OutOfStock; XS, M, L, XL InStock. Real
               price also lives at __NEXT_DATA__ props.pageProps.pdpPageProps.variants[*]
               .price (64). The same blob holds decoys: size-chart "value" entries
               '0','2','4'...'20', related products priced 40 / 68, and
               freeShippingPriceThreshold 75. None of those may ever be returned.
* tracksmith   JSON-LD Product, single Offer, price "95.0" (a string), USD, OutOfStock.
               The page also contains recommendation prices (19, 20, 85, 100, 280).
* lululemon, bloomingdales   Akamai 403 "Access Denied" pages. No price. Must give [].
"""

from __future__ import annotations

import re

import pytest

from extract.base import Extracted, extract
from tests.conftest import read_fixture, read_synthetic
from tests.test_normalize import ANTHRO_LONG, BLOOMIES, FARMRIO_LONG, LULU, TRACKSMITH

VUORI_URL = (
    "https://vuoriclothing.com/products/womens-daily-piped-bra-black"
    "?refSlotId=pdp-more-collection&objectId=41437918036071"
)
UNKNOWN_URL = "https://shop.example.test/products/synthetic-widget"

# (fixture filename fragment, url, expected price in cents)
PRICED = [
    pytest.param("farmrio", FARMRIO_LONG, 29800, id="farmrio"),
    pytest.param("anthropologie", ANTHRO_LONG, 17800, id="anthropologie"),
    pytest.param("vuori", VUORI_URL, 6400, id="vuori"),
    pytest.param("tracksmith", TRACKSMITH, 9500, id="tracksmith"),
]
NO_PRICE = [
    pytest.param("lululemon", LULU, id="lululemon-403"),
    pytest.param("bloomingdales", BLOOMIES, id="bloomingdales-403"),
]

VUORI_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
VUORI_IN_STOCK = {"xxs": False, "xs": True, "s": False, "m": True, "l": True, "xl": True, "xxl": False}


def assert_well_formed(results: list[Extracted]) -> None:
    """Shape rules every result must obey.

    variant_key rule (stated here, change if the owner prefers another):
    None when the variant is unknown; otherwise the lowercase string
    "<size>|<color>" - exactly one "|", each side stripped, lowercase, internal
    whitespace collapsed to single spaces, and no leading/trailing spaces.
    """
    assert isinstance(results, list)
    for r in results:
        assert isinstance(r, Extracted)
        assert type(r.price_cents) is int, f"price_cents must be int, got {type(r.price_cents)}"
        assert r.price_cents > 0
        assert r.currency == "USD"
        assert type(r.in_stock) is bool
        assert isinstance(r.strategy, str) and r.strategy.strip()
        if r.variant_key is not None:
            assert isinstance(r.variant_key, str)
            assert r.variant_key.count("|") == 1
            assert r.variant_key == r.variant_key.lower()
            assert r.variant_key == r.variant_key.strip()
            assert "  " not in r.variant_key
            size, color = r.variant_key.split("|")
            assert size == size.strip() and color == color.strip()


# ------------------------------------------------------------- real fixtures --

@pytest.mark.parametrize("name,url,cents", PRICED)
def test_expected_price_is_among_results(name, url, cents):
    results = extract(read_fixture(name), url)
    assert results, f"{name}: extract returned nothing"
    assert cents in [r.price_cents for r in results]


@pytest.mark.parametrize("name,url,cents", PRICED)
def test_every_returned_price_is_the_true_price(name, url, cents):
    # All four fixtures are unambiguous: every variant costs the same, and the
    # pages contain decoy prices (related products etc.) that must not leak.
    results = extract(read_fixture(name), url)
    assert results
    assert {r.price_cents for r in results} == {cents}


@pytest.mark.parametrize("name,url,cents", PRICED)
def test_results_are_well_formed(name, url, cents):
    results = extract(read_fixture(name), url)
    assert results
    assert_well_formed(results)


@pytest.mark.parametrize("name,url,cents", PRICED)
def test_results_are_deterministic(name, url, cents):
    html = read_fixture(name)
    assert extract(html, url) == extract(html, url)


@pytest.mark.parametrize("name,url,cents", PRICED)
def test_variant_keys_are_unique_when_present(name, url, cents):
    keys = [r.variant_key for r in extract(read_fixture(name), url) if r.variant_key is not None]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("name,url", NO_PRICE)
def test_blocked_pages_return_empty_list(name, url):
    results = extract(read_fixture(name), url)
    assert results == []


@pytest.mark.parametrize("name,url", NO_PRICE)
def test_blocked_fixtures_really_are_access_denied(name, url):
    # Guard the premise of the test above so a re-recorded fixture is noticed.
    assert "Access Denied" in read_fixture(name)
    extract(read_fixture(name), url)  # and the stub must be exercised


def test_url_tracking_params_do_not_change_results():
    html = read_fixture("farmrio")
    clean = (
        "https://farmrio.com/products/rustic-flowers-winter-white-sleeveless-maxi-dress"
        "?variant=44352681902173&country=US&currency=USD"
    )
    assert extract(html, FARMRIO_LONG) == extract(html, clean)


# ---------------------------------------------------------- farmrio specifics --

def test_farmrio_returns_one_result_per_offer():
    results = extract(read_fixture("farmrio"), FARMRIO_LONG)
    assert len(results) == 6
    assert all(r.in_stock is True for r in results)


# ----------------------------------------------------------- tracksmith stock --

# CONTRACT CHOICE: tracksmith has only a page-level JSON-LD Offer (OutOfStock), so no
# result may claim in_stock=True, even if other sizes are buyable in the Astro props.
def test_tracksmith_not_reported_in_stock():
    # The only structured Offer says schema.org/OutOfStock.
    results = extract(read_fixture("tracksmith"), TRACKSMITH)
    assert results
    # The page-level Offer is OutOfStock. A variant-level reading (the URL's
    # sku=WB716801BLK) must not contradict that with in_stock=True either.
    assert all(r.in_stock is False for r in results)


def test_tracksmith_string_price_converted_exactly():
    # JSON-LD has "95.0" (string, one decimal) -> 9500, not 950 or 95.
    results = extract(read_fixture("tracksmith"), TRACKSMITH)
    assert {r.price_cents for r in results} == {9500}


def test_anthropologie_in_stock():
    results = extract(read_fixture("anthropologie"), ANTHRO_LONG)
    assert results and all(r.in_stock is True for r in results)


# ------------------------------------------------------------------- Vuori ----

def test_vuori_one_result_per_size_with_expected_stock():
    results = extract(read_fixture("vuori"), VUORI_URL)
    assert len(results) == len(VUORI_SIZES)
    # variant_key rule: lowercase "size|color".
    by_key = {r.variant_key: r for r in results}
    assert set(by_key) == {f"{s.lower()}|black" for s in VUORI_SIZES}
    for size, expected in VUORI_IN_STOCK.items():
        assert by_key[f"{size}|black"].in_stock is expected, size


def test_vuori_size_run_never_appears_as_price():
    # Regression: key-name heuristics matched the size run 0,2,4..14 as prices.
    results = extract(read_fixture("vuori"), VUORI_URL)
    assert results
    returned = {r.price_cents for r in results}
    size_run = [0, 2, 4, 6, 8, 10, 12, 14]
    forbidden = {n * 100 for n in size_run} | set(size_run)
    # Also the rest of the fixture's size chart (0..20) and its denim waists.
    forbidden |= {n * 100 for n in range(0, 21, 2)} | set(range(0, 21))
    assert returned.isdisjoint(forbidden), returned & forbidden


def test_vuori_decoy_prices_never_returned():
    # Related products (40, 68 USD) and the free-shipping threshold (75) sit in
    # the same __NEXT_DATA__ blob as the real 64.
    returned = {r.price_cents for r in extract(read_fixture("vuori"), VUORI_URL)}
    assert returned.isdisjoint({4000, 6800, 7500})
    assert returned == {6400}


def test_vuori_fixture_premise_size_values_exist():
    # Guard: the decoys the regression test defends against are really there.
    html = read_fixture("vuori")
    for v in ("0", "2", "4", "6", "8", "10", "12", "14"):
        assert re.search(r'"value"\s*:\s*"%s"' % v, html), v
    extract(html, VUORI_URL)  # and the stub must be exercised


def test_vuori_price_found_without_json_ld():
    # Vuori's price also lives in __NEXT_DATA__; strip JSON-LD and it should
    # still be recoverable from the explicit variants[].price path.
    html = read_fixture("vuori")
    stripped = re.sub(
        r'<script[^>]*application/ld\+json[^>]*>.*?</script>', "", html, flags=re.S
    )
    assert "application/ld+json" not in stripped
    results = extract(stripped, VUORI_URL)
    assert results
    assert {r.price_cents for r in results} == {6400}
    assert_well_formed(results)


# --------------------------------------------------------- degenerate input ---

@pytest.mark.parametrize(
    "html",
    [
        "",
        "   \n\t ",
        "not html at all",
        "<html><body><p>Hello</p></body></html>",
        "<html><head><title>x</title></head><body><div",
        "\x00\x01\x02 garbage ��",
        "<script type='application/ld+json'>null</script>",
        "<script type='application/ld+json'>[]</script>",
        "<script type='application/ld+json'>{}</script>",
        '<script type="application/ld+json">"just a string"</script>',
    ],
    ids=["empty", "whitespace", "plain-text", "no-price-html", "truncated", "binary-ish",
         "ld-null", "ld-empty-list", "ld-empty-obj", "ld-string"],
)
def test_garbage_returns_empty_list(html):
    assert extract(html, UNKNOWN_URL) == []


def test_empty_url_does_not_raise():
    assert extract("", "") == []


# --------------------------------------------------------------- synthetic ----

def test_synthetic_generic_jsonld_fallback_on_unknown_domain():
    results = extract(read_synthetic("generic_jsonld_product.html"), UNKNOWN_URL)
    assert len(results) == 1
    # 19.99 is the classic float trap: int(19.99 * 100) == 1998.
    assert results[0].price_cents == 1999
    assert results[0].in_stock is True
    assert results[0].currency == "USD"
    assert_well_formed(results)


def test_synthetic_jsonld_price_string():
    results = extract(read_synthetic("jsonld_price_string.html"), UNKNOWN_URL)
    assert [r.price_cents for r in results] == [29800]
    assert_well_formed(results)


def test_synthetic_jsonld_price_with_thousands_separator():
    results = extract(read_synthetic("jsonld_price_thousands.html"), UNKNOWN_URL)
    assert [r.price_cents for r in results] == [129950]


def test_synthetic_graph_with_multiple_offers_keeps_per_offer_price_and_stock():
    results = extract(read_synthetic("jsonld_graph_multi_offer.html"), UNKNOWN_URL)
    assert len(results) == 2
    assert sorted((r.price_cents, r.in_stock) for r in results) == [(1999, True), (2499, False)]
    assert_well_formed(results)


def test_synthetic_product_without_offers_returns_empty():
    assert extract(read_synthetic("jsonld_no_offers.html"), UNKNOWN_URL) == []


def test_synthetic_offer_without_price_returns_empty():
    assert extract(read_synthetic("jsonld_no_price_in_offer.html"), UNKNOWN_URL) == []


# CONTRACT CHOICE: a JSON-LD price of 0 is a placeholder, not a price -> [].
def test_synthetic_zero_price_returns_empty():
    assert extract(read_synthetic("jsonld_zero_price.html"), UNKNOWN_URL) == []


def test_synthetic_malformed_jsonld_returns_empty_not_raises():
    assert extract(read_synthetic("jsonld_malformed.html"), UNKNOWN_URL) == []


def test_synthetic_price_key_holding_sizes_is_not_returned():
    # No JSON-LD; keys named price/value/amount/lowPrice/currentPrice hold size
    # numbers. Explicit paths only - never key-name heuristics.
    assert extract(read_synthetic("heuristic_trap_size_price_key.html"), UNKNOWN_URL) == []


def test_synthetic_trap_does_not_leak_even_with_real_domain_url():
    # Same trap page requested as if it were a known domain: still no guess.
    assert extract(read_synthetic("heuristic_trap_size_price_key.html"), VUORI_URL) == []
