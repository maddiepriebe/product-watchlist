import json
from pathlib import Path

import pytest

from extract.findpath import Location, find_paths, load_blobs
from extract.urlvariant import find_pinned_variant, url_selectors
from extract.variantkey import is_well_formed, variant_key

FIXTURES = Path(__file__).parent / "fixtures"
FARMRIO = "fixture-farmrio-com-products-rustic-flowers-winter-white-sleeveless-.html"
VUORI = "fixture-vuoriclothing-com-products-womens-daily-piped-bra-black-refS.html"
TRACKSMITH = "fixture-www-tracksmith-com-products-w-meridian-speed-shorts-sku-WB71.html"
ANTHRO = "fixture-www-anthropologie-com-shop-farm-rio-x-anthropologie-sleevele.html"

FARM_BASE = "https://farmrio.com/products/rustic-flowers-winter-white-sleeveless-maxi-dress"
VUORI_BASE = "https://vuoriclothing.com/products/womens-daily-piped-bra-black"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def value_at(html: str, loc: Location):
    blob = next(b for b in load_blobs(html) if b.kind == loc.blob and b.block == loc.block)
    node = blob.data
    for k in loc.path:
        node = node[k]
    return node


# ------------------------------------------------------------- variant_key

@pytest.mark.parametrize(
    "size, color, expected",
    [
        ("XS", "Black", "xs|black"),
        ("  Extra   Small ", "Painted\tWinter", "extra small|painted winter"),
        ("M", None, "m|"),
        (None, "Black", "|black"),
        (None, None, ""),
        ("", "  ", ""),
        ("a|b", "c", "a b|c"),
    ],
)
def test_variant_key(size: str | None, color: str | None, expected: str) -> None:
    assert variant_key(size, color) == expected
    assert is_well_formed(expected)


@pytest.mark.parametrize("bad", ["XS|black", "xs", "a|b|c", " xs|black", "xs|  black", None, 3])
def test_is_well_formed_rejects(bad: object) -> None:
    assert not is_well_formed(bad)


# ----------------------------------------------------------- url_selectors

def test_url_selectors_keeps_only_variant_picking_params() -> None:
    url = f"{FARM_BASE}?variant=44352681902173&country=US&utm_source=x&Color=Black&size="
    assert url_selectors(url) == {"variant": "44352681902173", "color": "Black"}


def test_url_selectors_none_when_absent_or_conflicting() -> None:
    assert url_selectors(FARM_BASE) is None
    assert url_selectors(f"{FARM_BASE}?country=US") is None
    assert url_selectors(f"{FARM_BASE}?variant=1&variant=2") is None


# ---------------------------------------------------------------- Farm Rio

def test_farmrio_variant_param_picks_the_matching_offer() -> None:
    html = fixture(FARMRIO)
    pinned = find_pinned_variant(html, f"{FARM_BASE}?variant=44352681902173&utm_source=google")
    assert pinned is not None
    [loc] = pinned.locations
    assert (loc.blob, loc.block, loc.path) == ("jsonld", 1, ("offers", 2))
    offer = value_at(html, loc)
    assert offer["sku"] == "196198770105"   # not offers[0]
    assert offer["url"].endswith("?variant=44352681902173")
    # The JSON-LD offers carry no size/color, so there is no key to pin by.
    assert (pinned.size, pinned.color, pinned.key) == (None, None, "")


def test_farmrio_each_variant_param_picks_its_own_offer() -> None:
    html = fixture(FARMRIO)
    for i, vid in enumerate(
        ["44352681836637", "44352681869405", "44352681902173",
         "44352681934941", "44352681967709", "44352682000477"]
    ):
        pinned = find_pinned_variant(html, f"{FARM_BASE}?variant={vid}")
        assert pinned is not None and pinned.locations[0].path == ("offers", i)


def test_farmrio_sku_param_matches_offer_sku() -> None:
    html = fixture(FARMRIO)
    pinned = find_pinned_variant(html, f"{FARM_BASE}?sku=196198770129")
    assert pinned is not None and pinned.locations[0].path == ("offers", 4)


def test_farmrio_products_own_sku_does_not_pick_among_several_offers() -> None:
    # The Product-level sku equals offers[2]'s, but the Product has six offers,
    # so only the offers' own ids may be used.
    html = fixture(FARMRIO)
    pinned = find_pinned_variant(html, f"{FARM_BASE}?sku=196198770105")
    assert pinned is not None and pinned.locations[0].path == ("offers", 2)


def test_url_without_variant_param_is_none() -> None:
    html = fixture(FARMRIO)
    assert find_pinned_variant(html, FARM_BASE) is None
    assert find_pinned_variant(html, f"{FARM_BASE}?country=US&currency=USD") is None


def test_unknown_variant_is_none() -> None:
    assert find_pinned_variant(fixture(FARMRIO), f"{FARM_BASE}?variant=999") is None


def test_ambiguous_match_is_none() -> None:
    # color alone is shared by every Vuori size, so it names no single offer.
    assert find_pinned_variant(fixture(VUORI), f"{VUORI_BASE}?color=Black") is None
    # A duplicated offer (same id twice) is also ambiguous.
    blob = json.dumps({
        "@type": "Product",
        "offers": [{"@type": "Offer", "sku": "A", "price": 1}, {"@type": "Offer", "sku": "A", "price": 1}],
    })
    page = f'<script type="application/ld+json">{blob}</script>'
    assert find_pinned_variant(page, "https://x.test/p?sku=A") is None


def test_conflicting_selectors_are_none() -> None:
    # variant picks offers[2] but sku names a different offer.
    url = f"{FARM_BASE}?variant=44352681902173&sku=196198770082"
    assert find_pinned_variant(fixture(FARMRIO), url) is None


# --------------------------------------------------------------- Tracksmith

def test_tracksmith_sku_matches_the_products_only_offer() -> None:
    html = fixture(TRACKSMITH)
    pinned = find_pinned_variant(html, "https://www.tracksmith.com/products/w-meridian-speed-shorts?sku=WB716801BLK")
    assert pinned is not None
    [loc] = pinned.locations
    assert (loc.blob, loc.block, loc.path) == ("jsonld", 0, ("offers",))
    assert value_at(html, loc)["price"] == "95.0"


def test_tracksmith_other_sku_is_none() -> None:
    url = "https://www.tracksmith.com/products/w-meridian-speed-shorts?sku=WB716802BLK"
    assert find_pinned_variant(fixture(TRACKSMITH), url) is None


# ------------------------------------------------------------------- Vuori

def test_vuori_object_id_matches_jsonld_and_next_data_with_size_and_color() -> None:
    html = fixture(VUORI)
    pinned = find_pinned_variant(html, f"{VUORI_BASE}?objectId=41437918036071")
    assert pinned is not None
    paths = {(loc.blob, loc.path) for loc in pinned.locations}
    assert paths == {
        ("jsonld", ("hasVariant", 1, "offers")),
        ("nextdata", ("props", "pageProps", "pdpPageProps", "variants", 1)),
    }
    assert (pinned.size, pinned.color, pinned.key) == ("XS", "Black", "xs|black")


def test_vuori_sku_matches() -> None:
    pinned = find_pinned_variant(fixture(VUORI), f"{VUORI_BASE}?sku=VW1279BLKXXS")
    assert pinned is not None and pinned.key == "xxs|black"


def test_vuori_size_and_color_together_pick_one() -> None:
    pinned = find_pinned_variant(fixture(VUORI), f"{VUORI_BASE}?color=black&size=xs")
    assert pinned is not None and pinned.key == "xs|black"


def test_vuori_next_data_only() -> None:
    html = fixture(VUORI).replace('type="application/ld+json"', 'type="text/disabled"')
    pinned = find_pinned_variant(html, f"{VUORI_BASE}?objectId=41437918036071")
    assert pinned is not None
    assert [loc.blob for loc in pinned.locations] == ["nextdata"]
    assert pinned.key == "xs|black"


def test_pinned_vuori_price_path_is_preferred() -> None:
    html = fixture(VUORI)
    pinned = find_pinned_variant(html, f"{VUORI_BASE}?objectId=41437918036071")
    assert pinned is not None
    first = find_paths(html, 6400, pinned.locations)[0]
    assert first.blob == "jsonld" and first.path == ("hasVariant", 1, "offers", "price")
    assert find_paths(html, 6400)[0].path != first.path   # without the pin, another offer wins


# ------------------------------------------------------------- Anthropologie

def test_anthropologie_color_code_matches_nothing() -> None:
    # `color=627` is a retailer code that no structured data states.
    url = "https://www.anthropologie.com/shop/farm-rio-x-anthropologie-sleeveless-mesh-midi-dress?color=627"
    assert find_pinned_variant(fixture(ANTHRO), url) is None


# ------------------------------------------------------------- find_paths

def test_find_paths_prefers_the_pinned_offer() -> None:
    html = fixture(FARMRIO)
    pinned = find_pinned_variant(html, f"{FARM_BASE}?variant=44352681902173")
    assert pinned is not None
    cands = find_paths(html, 29800, pinned.locations)
    assert cands[0].path == ("offers", 2, "price")
    assert cands[0].within(pinned.locations[0])
    # Everything is still offered, just reordered.
    assert {c.path for c in cands} == {c.path for c in find_paths(html, 29800)}
    assert find_paths(html, 29800)[0].path == ("offers", 0, "price")
