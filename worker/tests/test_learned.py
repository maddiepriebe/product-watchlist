import json
from pathlib import Path

import pytest

from extract.findpath import find_paths
from extract.learned import availability_in_stock, resolve

FIXTURES = Path(__file__).parent / "fixtures"
FARMRIO = "fixture-farmrio-com-products-rustic-flowers-winter-white-sleeveless-.html"
VUORI = "fixture-vuoriclothing-com-products-womens-daily-piped-bra-black-refS.html"
TRACKSMITH = "fixture-www-tracksmith-com-products-w-meridian-speed-shorts-sku-WB71.html"
ANTHRO = "fixture-www-anthropologie-com-shop-farm-rio-x-anthropologie-sleevele.html"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "name, cents",
    [(FARMRIO, 29800), (VUORI, 6400), (TRACKSMITH, 9500), (ANTHRO, 17800)],
)
def test_every_candidate_round_trips(name: str, cents: int) -> None:
    html = fixture(name)
    cands = find_paths(html, cents)
    assert cands
    for c in cands:
        # Through JSON, as it would be stored in extractor_config.
        cfg = json.loads(json.dumps(c.config()))
        [got] = resolve(html, cfg)
        assert got.price_cents == cents
        assert got.variant_key is None
        assert got.strategy == f"learned:{c.blob}"


def test_vuori_next_data_round_trip() -> None:
    html = fixture(VUORI)
    cfg = {
        "learned": True, "blob": "nextdata",
        "path": ["props", "pageProps", "pdpPageProps", "variants", 0, "price"],
        "unit": "major",
    }
    [got] = resolve(html, cfg)
    assert got.price_cents == 6400
    assert got.currency == "USD"


def test_jsonld_availability_sibling_sets_stock() -> None:
    # Tracksmith's fixture offer is OutOfStock; Farm Rio's are InStock.
    [ts] = resolve(fixture(TRACKSMITH), find_paths(fixture(TRACKSMITH), 9500)[0].config())
    assert ts.in_stock is False
    assert ts.currency == "USD"
    [fr] = resolve(fixture(FARMRIO), find_paths(fixture(FARMRIO), 29800)[0].config())
    assert fr.in_stock is True


def test_broken_path_returns_empty() -> None:
    html = fixture(FARMRIO)
    good = find_paths(html, 29800)[0].config()
    assert resolve(html, {**good, "path": ["offers", 99, "price"]}) == []
    assert resolve(html, {**good, "path": ["offers", 0, "nope"]}) == []
    assert resolve(html, {**good, "path": ["offers", 0, "sku", "x"]}) == []
    assert resolve(html, {**good, "block": 7}) == []
    assert resolve(html, {**good, "blob": "nextdata"}) == []


def test_path_to_non_number_returns_empty() -> None:
    html = fixture(FARMRIO)
    cfg = {"learned": True, "blob": "jsonld", "block": 1, "path": ["name"], "unit": "major"}
    assert resolve(html, cfg) == []


def test_layout_change_breaks_path() -> None:
    old = '<script type="application/ld+json">{"offers": {"price": "298.00"}}</script>'
    new = '<script type="application/ld+json">{"offers": [{"price": "298.00"}]}</script>'
    cfg = find_paths(old, 29800)[0].config()
    assert resolve(old, cfg)[0].price_cents == 29800
    assert resolve(new, cfg) == []


def test_price_change_is_read() -> None:
    cfg = {"learned": True, "blob": "jsonld", "block": 0, "path": ["offers", "price"], "unit": "major"}
    html = '<script type="application/ld+json">{"offers": {"price": 248.5}}</script>'
    assert resolve(html, cfg)[0].price_cents == 24850


def test_minor_unit_must_be_integral() -> None:
    cfg = {"learned": True, "blob": "nextdata", "path": ["p"], "unit": "minor"}
    ok = '<script id="__NEXT_DATA__">{"p": 29800}</script>'
    bad = '<script id="__NEXT_DATA__">{"p": 298.5}</script>'
    assert resolve(ok, cfg)[0].price_cents == 29800
    assert resolve(bad, cfg) == []


def test_sub_cent_major_value_is_rejected() -> None:
    cfg = {"learned": True, "blob": "nextdata", "path": ["p"], "unit": "major"}
    assert resolve('<script id="__NEXT_DATA__">{"p": 19.999}</script>', cfg) == []


@pytest.mark.parametrize(
    "cfg",
    [
        {},
        {"learned": False, "blob": "jsonld", "block": 0, "path": ["price"], "unit": "major"},
        {"learned": True, "blob": "css", "path": ["price"], "unit": "major"},
        {"learned": True, "blob": "jsonld", "path": ["price"], "unit": "major"},  # no block
        {"learned": True, "blob": "jsonld", "block": 0, "path": [], "unit": "major"},
        {"learned": True, "blob": "jsonld", "block": 0, "path": ["price"], "unit": "cents"},
        {"learned": True, "blob": "jsonld", "block": 0, "path": [1.5], "unit": "major"},
    ],
)
def test_invalid_config_returns_empty(cfg: dict) -> None:
    html = '<script type="application/ld+json">{"price": 10}</script>'
    assert resolve(html, cfg) == []


def test_currency_from_sibling() -> None:
    cfg = {"learned": True, "blob": "jsonld", "block": 0, "path": ["offers", "price"], "unit": "major"}
    html = '<script type="application/ld+json">{"offers": {"price": 10, "priceCurrency": "cad"}}</script>'
    assert resolve(html, cfg)[0].currency == "CAD"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("http://schema.org/InStock", True),
        ("https://schema.org/OutOfStock", False),
        ("SoldOut", False),
        ("https://schema.org/LimitedAvailability", True),
        ("https://schema.org/PreOrder", False),
        ("", None),
        (None, None),
        (True, None),
    ],
)
def test_availability(value: object, expected: bool | None) -> None:
    assert availability_in_stock(value) is expected
