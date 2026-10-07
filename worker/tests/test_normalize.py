"""Tests for extract.normalize.normalize_url -> (canonical_url, url_hash)."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

import pytest

from extract.normalize import normalize_url

# Original full URLs from scripts/spike.py (Google-ads tracking params intact).
FARMRIO_LONG = (
    "https://farmrio.com/products/rustic-flowers-winter-white-sleeveless-maxi-dress"
    "?variant=44352681902173&country=US&currency=USD&utm_medium=product_sync"
    "&utm_source=google&utm_content=sag_organic&utm_campaign=sag_organic"
    "&utm_id=22691767564&gad_source=1&gad_campaignid=22682102067"
    "&gbraid=0AAAAAC4GiQ_6Jqory_gos8887s2z-ljWi"
    "&gclid=Cj0KCQjwnIDUBhDrARIsAJDGwStufm1xGkXls0kiCRJvtTDNRd0YEh3FdTfEBKzjcfP34U-Ve2Fo1U0aAie-EALw_wcB"
)
FARMRIO_CLEAN = (
    "https://farmrio.com/products/rustic-flowers-winter-white-sleeveless-maxi-dress"
    "?variant=44352681902173&country=US&currency=USD"
)
ANTHRO_LONG = (
    "https://www.anthropologie.com/shop/farm-rio-x-anthropologie-sleeveless-mesh-midi-dress"
    "?color=627&inventoryCountry=US&countryCode=US&creative=&device=c"
    "&g_acctid=619-693-8226&g_adgroupid=&g_adid=&g_adtype=none"
    "&g_campaign=US+-+Shopping+-+PMAX+-+Apparel+-+Dresses+-+General"
    "&g_campaignid=19807768742&g_keyword=&g_keywordid=&g_network=x&g_type=shopping"
    "&matchtype=&network=x"
    "&utm_campaign=US+-+Shopping+-+PMAX+-+Apparel+-+Dresses+-+General"
    "&utm_content=&utm_kxconfid=vx6rd81ts&utm_medium=paid_search&utm_source=Google&utm_term="
    "&gclsrc=aw.ds&gad_source=1&gad_campaignid=19800408132"
    "&gbraid=0AAAAADnwqi6XmdBNNA51Ff8hMfEwWVHzB"
    "&gclid=Cj0KCQjwnIDUBhDrARIsAJDGwSt6KtsShJLMfTn3kdhdiC2TL2wpOLono7utW2JkIjbevMB91uESoe4aAo5EEALw_wcB"
)
ANTHRO_CLEAN = (
    "https://www.anthropologie.com/shop/farm-rio-x-anthropologie-sleeveless-mesh-midi-dress"
    "?color=627&inventoryCountry=US&countryCode=US"
)
BLOOMIES = (
    "https://www.bloomingdales.com/shop/product/maje-rishell-gold-jewelry-knit-midi-dress"
    "?ID=5855482#PRODUCT_DEPARTMENT/Dresses"
)
TRACKSMITH = "https://www.tracksmith.com/products/w-meridian-speed-shorts?sku=WB716801BLK"
LULU = (
    "https://shop.lululemon.com/p/women-shorts/Speed-Up-High-Rise-Short-4-Updated-MD/_/prod11900032"
    "?fp=1&color=62328"
)

# Every tracking param name that appears in the two long URLs, with a value.
TRACKING_PARAMS = {
    "utm_medium": "product_sync",
    "utm_source": "google",
    "utm_content": "sag_organic",
    "utm_campaign": "sag_organic",
    "utm_id": "22691767564",
    "utm_term": "red dress",
    "utm_kxconfid": "vx6rd81ts",
    "gad_source": "1",
    "gad_campaignid": "22682102067",
    "gbraid": "0AAAAAC4GiQ_6Jqory_gos8887s2z-ljWi",
    "gclid": "Cj0KCQjwnIDUBhDrARIsAJDGwStufm1xGkXls0kiCRJvtTDNRd0YEh3FdTfEBKzjcfP34U",
    "gclsrc": "aw.ds",
    "g_acctid": "619-693-8226",
    "g_adgroupid": "123",
    "g_adid": "456",
    "g_adtype": "none",
    "g_campaign": "US - Shopping",
    "g_campaignid": "19807768742",
    "g_keyword": "dress",
    "g_keywordid": "789",
    "g_network": "x",
    "g_type": "shopping",
    "creative": "999",
    "device": "c",
    "network": "x",
    "matchtype": "b",
}
# Names the canonical URL must never contain (matched by name or prefix).
TRACKING_PREFIXES = ("utm_", "gad_", "g_")
TRACKING_NAMES = {"gbraid", "gclid", "gclsrc", "creative", "device", "network", "matchtype"}
PRESERVED = {"variant", "color", "size", "sku", "country", "currency"}


def params_of(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))


def is_tracking(name: str) -> bool:
    return name in TRACKING_NAMES or name.startswith(TRACKING_PREFIXES)


def with_query(base: str, extra: str) -> str:
    return base + ("&" if "?" in base else "?") + extra


# ------------------------------------------------------------ return types --

def test_returns_tuple_of_two_nonempty_strings():
    result = normalize_url(FARMRIO_LONG)
    assert isinstance(result, tuple)
    assert len(result) == 2
    canonical, url_hash = result
    assert isinstance(canonical, str) and canonical
    assert isinstance(url_hash, str) and url_hash


def test_hash_is_deterministic_across_calls():
    assert normalize_url(FARMRIO_LONG) == normalize_url(FARMRIO_LONG)
    assert normalize_url(FARMRIO_LONG)[1] == normalize_url(FARMRIO_LONG)[1]


def test_hash_has_no_whitespace_and_is_a_single_token():
    # Don't constrain the algorithm; just make sure it is safe as a DB key.
    _, h = normalize_url(TRACKSMITH)
    assert h == h.strip() and " " not in h and "\n" not in h


def test_different_products_have_different_hashes():
    hashes = {normalize_url(u)[1] for u in (FARMRIO_CLEAN, ANTHRO_CLEAN, BLOOMIES, TRACKSMITH, LULU)}
    assert len(hashes) == 5


def test_canonical_is_idempotent():
    for url in (FARMRIO_LONG, ANTHRO_LONG, BLOOMIES, TRACKSMITH):
        canonical, h = normalize_url(url)
        assert normalize_url(canonical) == (canonical, h)


# ------------------------------------------------------- tracking stripping --

@pytest.mark.parametrize("url", [FARMRIO_LONG, ANTHRO_LONG], ids=["farmrio", "anthropologie"])
def test_no_tracking_param_survives_in_canonical(url):
    canonical, _ = normalize_url(url)
    params = params_of(canonical)
    leaked = [n for n in params if is_tracking(n)]
    assert leaked == []


@pytest.mark.parametrize("url", [FARMRIO_LONG, ANTHRO_LONG], ids=["farmrio", "anthropologie"])
def test_no_empty_valued_param_survives_in_canonical(url):
    canonical, _ = normalize_url(url)
    empties = [n for n, v in params_of(canonical).items() if v == ""]
    assert empties == []


def test_canonical_does_not_contain_tracking_substrings():
    for url in (FARMRIO_LONG, ANTHRO_LONG):
        canonical, _ = normalize_url(url)
        for needle in ("utm_", "gclid", "gbraid", "gclsrc", "gad_", "g_acctid", "matchtype"):
            assert needle not in canonical


def test_farmrio_preserves_variant_country_currency():
    canonical, _ = normalize_url(FARMRIO_LONG)
    params = params_of(canonical)
    assert params["variant"] == "44352681902173"
    assert params["country"] == "US"
    assert params["currency"] == "USD"
    assert set(params) == {"variant", "country", "currency"}


def test_anthropologie_preserves_color():
    canonical, _ = normalize_url(ANTHRO_LONG)
    assert params_of(canonical)["color"] == "627"


def test_preserved_params_survive_by_name():
    url = "https://example.com/p/thing?variant=1&color=red&size=M&sku=ABC&country=US&currency=USD"
    params = params_of(normalize_url(url)[0])
    assert params == {
        "variant": "1", "color": "red", "size": "M", "sku": "ABC",
        "country": "US", "currency": "USD",
    }


def test_scheme_host_and_path_preserved():
    canonical, _ = normalize_url(FARMRIO_LONG)
    parts = urlsplit(canonical)
    assert parts.scheme == "https"
    assert parts.netloc == "farmrio.com"
    assert parts.path == "/products/rustic-flowers-winter-white-sleeveless-maxi-dress"


def test_tracksmith_sku_is_kept():
    canonical, _ = normalize_url(TRACKSMITH)
    assert params_of(canonical) == {"sku": "WB716801BLK"}


def test_empty_valued_param_with_unknown_name_is_dropped():
    # Per docstring: "any param with an empty value" is stripped.
    canonical, h = normalize_url("https://example.com/p?variant=1&refslot=")
    assert "refslot" not in canonical
    assert h == normalize_url("https://example.com/p?variant=1")[1]


def test_empty_valued_preserved_param_is_dropped_too():
    canonical, _ = normalize_url("https://example.com/p?variant=&color=red")
    assert params_of(canonical) == {"color": "red"}


# ------------------------------------------------------------------ hashing --

@pytest.mark.parametrize("url_long,url_clean", [(FARMRIO_LONG, FARMRIO_CLEAN), (ANTHRO_LONG, ANTHRO_CLEAN)],
                         ids=["farmrio", "anthropologie"])
def test_long_url_hashes_same_as_tracking_stripped_url(url_long, url_clean):
    assert normalize_url(url_long)[1] == normalize_url(url_clean)[1]
    assert normalize_url(url_long)[0] == normalize_url(url_clean)[0]


@pytest.mark.parametrize("name", sorted(TRACKING_PARAMS))
def test_adding_a_single_tracking_param_does_not_change_hash(name):
    base = normalize_url(FARMRIO_CLEAN)
    noisy = with_query(FARMRIO_CLEAN, f"{name}={TRACKING_PARAMS[name].replace(' ', '+')}")
    assert normalize_url(noisy) == base


@pytest.mark.parametrize("name", sorted(TRACKING_PARAMS))
def test_removing_a_single_tracking_param_does_not_change_hash(name):
    # Start from a URL carrying ALL tracking params; drop one at a time.
    all_params = "&".join(f"{k}={v.replace(' ', '+')}" for k, v in TRACKING_PARAMS.items())
    full = with_query(FARMRIO_CLEAN, all_params)
    without = with_query(
        FARMRIO_CLEAN,
        "&".join(f"{k}={v.replace(' ', '+')}" for k, v in TRACKING_PARAMS.items() if k != name),
    )
    assert normalize_url(full) == normalize_url(without) == normalize_url(FARMRIO_CLEAN)


def test_changing_a_tracking_param_value_does_not_change_hash():
    a = with_query(FARMRIO_CLEAN, "gclid=AAA&utm_source=google")
    b = with_query(FARMRIO_CLEAN, "gclid=BBB&utm_source=newsletter")
    assert normalize_url(a) == normalize_url(b)


@pytest.mark.parametrize("param", ["variant", "color", "sku"])
def test_urls_differing_only_in_identity_param_hash_differently(param):
    a = f"https://example.com/p/thing?{param}=111"
    b = f"https://example.com/p/thing?{param}=222"
    assert normalize_url(a)[1] != normalize_url(b)[1]
    assert normalize_url(a)[0] != normalize_url(b)[0]


def test_size_differences_change_hash():
    a = "https://example.com/p/thing?size=S"
    b = "https://example.com/p/thing?size=L"
    assert normalize_url(a)[1] != normalize_url(b)[1]


def test_variant_vs_no_variant_hashes_differently():
    assert normalize_url(FARMRIO_CLEAN)[1] != normalize_url(
        "https://farmrio.com/products/rustic-flowers-winter-white-sleeveless-maxi-dress?country=US&currency=USD"
    )[1]


def test_different_paths_hash_differently():
    assert normalize_url("https://example.com/p/a?variant=1")[1] != normalize_url(
        "https://example.com/p/b?variant=1"
    )[1]


# ------------------------------------------------------------ param ordering --

def test_param_reordering_gives_same_hash_and_canonical():
    a = "https://example.com/p?variant=1&color=red&size=M"
    b = "https://example.com/p?size=M&variant=1&color=red"
    c = "https://example.com/p?color=red&size=M&variant=1"
    assert normalize_url(a) == normalize_url(b) == normalize_url(c)


def test_reordering_with_interleaved_tracking_gives_same_result():
    a = "https://example.com/p?variant=1&utm_source=x&color=red&gclid=abc"
    b = "https://example.com/p?gclid=zzz&color=red&utm_source=y&variant=1"
    assert normalize_url(a) == normalize_url(b)


def test_canonical_params_are_sorted():
    canonical, _ = normalize_url("https://example.com/p?variant=1&color=red&size=M&sku=A")
    names = [n for n, _ in parse_qsl(urlsplit(canonical).query)]
    assert names == sorted(names)


# ------------------------------------------------------------- host + fragment

def test_host_is_lowercased_in_canonical_and_hash():
    mixed = "https://WWW.Farmrio.com/products/x?variant=1"
    lower = "https://www.farmrio.com/products/x?variant=1"
    assert normalize_url(mixed) == normalize_url(lower)
    assert urlsplit(normalize_url(mixed)[0]).netloc == "www.farmrio.com"


def test_fragment_is_dropped():
    canonical, h = normalize_url(BLOOMIES)
    assert "#" not in canonical
    assert "PRODUCT_DEPARTMENT" not in canonical
    assert h == normalize_url(BLOOMIES.split("#")[0])[1]


def test_fragment_value_does_not_affect_hash():
    a = normalize_url("https://example.com/p?variant=1#reviews")
    b = normalize_url("https://example.com/p?variant=1#details")
    c = normalize_url("https://example.com/p?variant=1")
    assert a == b == c


def test_bloomingdales_keeps_id_param():
    # ID is the product identity on bloomingdales; it is not a tracking param.
    canonical, _ = normalize_url(BLOOMIES)
    assert params_of(canonical) == {"ID": "5855482"}


def test_url_without_query_is_ok():
    canonical, h = normalize_url("https://example.com/products/thing")
    assert canonical == "https://example.com/products/thing"
    assert h


def test_url_with_only_tracking_equals_url_without_query():
    assert normalize_url("https://example.com/products/thing?utm_source=a&gclid=b") == normalize_url(
        "https://example.com/products/thing"
    )
