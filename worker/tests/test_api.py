from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from api import create_app, extractor_kind, retailer_of
from config import Settings
from extract import base as extract_base
from extract import normalize
from extract.base import Extracted
from extract.learned import resolve
from fetcher import FetchResult

FIXTURES = Path(__file__).parent / "fixtures"
SECRET = "s3cret-token"
AUTH = {"Authorization": f"Bearer {SECRET}"}
FARMRIO_URL = "https://farmrio.com/products/rustic-flowers-winter-white-sleeveless-maxi-dress?variant=44352681902173"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    def __init__(self, result: FetchResult | None = None) -> None:
        self.result = result or FetchResult("ok", FARMRIO_URL, 200, "<html></html>")
        self.urls: list[str] = []

    async def fetch(self, url: str) -> FetchResult:
        self.urls.append(url)
        return self.result

    async def aclose(self) -> None:
        pass


def page(name: str) -> FetchResult:
    return FetchResult("ok", FARMRIO_URL, 200, fixture(name))


@pytest.fixture
def fetcher() -> FakeFetcher:
    return FakeFetcher()


@pytest.fixture
def client(fetcher: FakeFetcher) -> Iterator[TestClient]:
    app = create_app(Settings(worker_shared_secret=SECRET), fetcher)  # type: ignore[arg-type]
    with TestClient(app) as c:
        yield c


@pytest.fixture
def normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(normalize, "normalize_url", lambda url: (url.split("&")[0], "hash-123"))


def post(client: TestClient, body: dict[str, Any], headers: dict[str, str] = AUTH) -> dict[str, Any]:
    r = client.post("/extract", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ auth

def test_healthz_needs_no_auth(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": SECRET},
     {"Authorization": f"Basic {SECRET}"}, {"Authorization": "Bearer "}],
)
def test_extract_requires_bearer(client: TestClient, headers: dict[str, str]) -> None:
    r = client.post("/extract", json={"url": FARMRIO_URL}, headers=headers)
    assert r.status_code == 401


def test_bearer_scheme_is_case_insensitive(client: TestClient, normalized: None) -> None:
    r = client.post("/extract", json={"url": "ftp://x"}, headers={"Authorization": f"bearer {SECRET}"})
    assert r.status_code == 200


def test_malformed_body_is_422(client: TestClient) -> None:
    assert client.post("/extract", json={"price_text": "$1"}, headers=AUTH).status_code == 422
    assert client.post("/extract", content=b"not json", headers={**AUTH, "Content-Type": "application/json"}).status_code == 422


def test_empty_secret_never_authorizes(fetcher: FakeFetcher) -> None:
    app = create_app(Settings(worker_shared_secret=""), fetcher)  # type: ignore[arg-type]
    with TestClient(app) as c:
        assert c.post("/extract", json={"url": FARMRIO_URL}, headers={"Authorization": "Bearer "}).status_code == 401


# --------------------------------------------------------------- statuses

@pytest.mark.parametrize("url", ["farmrio.com/products/x", "ftp://farmrio.com/x", "javascript:alert(1)", "https://", ""])
def test_invalid_url(client: TestClient, url: str) -> None:
    body = post(client, {"url": url})
    assert body == {"status": "invalid_url", "message": body["message"], "source": None, "variants": [],
                    "url_variant_key": None}
    assert body["message"].startswith("That doesn't look like a product link.")


def test_normalize_stub_is_not_implemented_without_source(client: TestClient, fetcher: FakeFetcher) -> None:
    body = post(client, {"url": FARMRIO_URL})   # real stub raises
    assert body["status"] == "not_implemented"
    assert body["source"] is None
    assert fetcher.urls == []


def test_extract_stub_is_not_implemented_with_source(client: TestClient, fetcher: FakeFetcher, normalized: None) -> None:
    fetcher.result = page("fixture-farmrio-com-products-rustic-flowers-winter-white-sleeveless-.html")
    body = post(client, {"url": FARMRIO_URL})   # real extract stub raises
    assert body["status"] == "not_implemented"
    src = body["source"]
    assert src["canonical_url"] == FARMRIO_URL and src["url_hash"] == "hash-123"
    assert src["retailer"] == "farmrio.com"
    assert src["title"] == "Multicolor Rustic Flowers Sleeveless Ruched Maxi Dress"
    assert src["extractor_config"] == {} and src["needs_browser"] is False
    assert body["variants"] == []
    assert "Enter the price you see" in body["message"]


def test_ok_from_registry_extract(client: TestClient, fetcher: FakeFetcher, normalized: None,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_base, "extract", lambda html, url: [
        Extracted(29800, "USD", True, "M|black", "jsonld"),
        Extracted(24800, "usd", False, None, "jsonld"),
    ])
    body = post(client, {"url": FARMRIO_URL})
    assert body["status"] == "ok"
    assert body["source"]["extractor"] == "jsonld"
    assert body["variants"] == [
        {"variant_key": "M|black", "size": "M", "color": "black", "price_cents": 29800, "currency": "USD", "in_stock": True},
        {"variant_key": "", "size": None, "color": None, "price_cents": 24800, "currency": "USD", "in_stock": False},
    ]
    assert body["message"] == "Found 2 variants at $248.00 to $298.00. Check they match the page before you save."
    assert fetcher.urls == [FARMRIO_URL]   # fetched the canonical URL


def test_no_price(client: TestClient, normalized: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_base, "extract", lambda html, url: [])
    body = post(client, {"url": FARMRIO_URL})
    assert body["status"] == "no_price"
    assert body["source"] is not None and body["variants"] == []


def test_invalid_extraction_is_no_price(client: TestClient, normalized: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_base, "extract", lambda html, url: [Extracted(298.0, "USD", True, None, "jsonld")])  # type: ignore[arg-type]
    assert post(client, {"url": FARMRIO_URL})["status"] == "no_price"


def test_blocked(client: TestClient, fetcher: FakeFetcher, normalized: None) -> None:
    fetcher.result = FetchResult("blocked", FARMRIO_URL, 403, error="HTTP 403")
    body = post(client, {"url": FARMRIO_URL})
    assert body["status"] == "blocked"
    assert body["source"]["retailer"] == "farmrio.com"
    assert "bot protection" in body["message"]


def test_fetch_failed(client: TestClient, fetcher: FakeFetcher, normalized: None) -> None:
    fetcher.result = FetchResult("http_error", FARMRIO_URL, 404, error="HTTP 404")
    body = post(client, {"url": FARMRIO_URL})
    assert body["status"] == "fetch_failed"
    assert body["message"] == "We couldn't load that page (HTTP 404). Check the link and try again."


# ------------------------------------------------------------- price_text

def test_price_text_teaches_a_path(client: TestClient, fetcher: FakeFetcher, normalized: None) -> None:
    fetcher.result = page("fixture-farmrio-com-products-rustic-flowers-winter-white-sleeveless-.html")
    body = post(client, {"url": FARMRIO_URL, "price_text": "$298.00"})
    assert body["status"] == "ok"
    src = body["source"]
    assert src["extractor"] == "jsonld"
    assert src["extractor_config"] == {
        "learned": True, "blob": "jsonld", "block": 1, "path": ["offers", 2, "price"], "unit": "major"}   # the offer FARMRIO_URL's ?variant= names
    assert body["variants"] == [
        {"variant_key": "", "size": None, "color": None, "price_cents": 29800, "currency": "USD", "in_stock": True}]
    assert body["url_variant_key"] is None   # Farm Rio's JSON-LD offers state no size or color
    # what the app stores is what the scheduler will read back
    assert resolve(fetcher.result.html, src["extractor_config"])[0].price_cents == 29800


VUORI_FILE = "fixture-vuoriclothing-com-products-womens-daily-piped-bra-black-refS.html"
VUORI_URL = "https://vuoriclothing.com/products/womens-daily-piped-bra-black"
TWO_SIZES = """<script type="application/ld+json">{"@type": "Product", "offers": [
  {"@type": "Offer", "sku": "A-S", "size": "S", "color": "Red", "price": 100},
  {"@type": "Offer", "sku": "A-M", "size": "M", "color": "Red", "price": 200}]}</script>"""


def test_price_text_pins_the_variant_the_url_names(client: TestClient, fetcher: FakeFetcher, normalized: None) -> None:
    fetcher.result = FetchResult("ok", VUORI_URL, 200, fixture(VUORI_FILE))
    body = post(client, {"url": f"{VUORI_URL}?objectId=41437918036071", "price_text": "$64"})
    assert body["status"] == "ok"
    cfg = body["source"]["extractor_config"]
    assert cfg == {
        "learned": True, "blob": "jsonld", "block": 0, "path": ["hasVariant", 1, "offers", "price"],
        "unit": "major", "variant_key": "xs|black", "size": "XS", "color": "Black"}
    assert body["url_variant_key"] == "xs|black"
    assert body["variants"] == [
        {"variant_key": "xs|black", "size": "xs", "color": "black", "price_cents": 6400,
         "currency": "USD", "in_stock": True}]
    assert resolve(fetcher.result.html, cfg)[0].variant_key == "xs|black"


def test_price_text_without_a_pinned_variant_has_no_key(client: TestClient, fetcher: FakeFetcher, normalized: None) -> None:
    fetcher.result = FetchResult("ok", VUORI_URL, 200, fixture(VUORI_FILE))
    body = post(client, {"url": VUORI_URL, "price_text": "$64"})
    assert body["status"] == "ok"
    assert "variant_key" not in body["source"]["extractor_config"]
    assert body["url_variant_key"] is None
    assert body["variants"][0]["variant_key"] == ""


def test_price_outside_the_pinned_offer_is_not_labelled(
    client: TestClient, fetcher: FakeFetcher, normalized: None
) -> None:
    # The URL names size S ($100) but the user typed $200, which only size M has.
    # We still learn the path they asked for, but must not call it size S.
    fetcher.result = FetchResult("ok", "https://x.test/p", 200, TWO_SIZES)
    body = post(client, {"url": "https://x.test/p?sku=A-S", "price_text": "200"})
    assert body["status"] == "ok"
    assert body["source"]["extractor_config"]["path"] == ["offers", 1, "price"]
    assert "variant_key" not in body["source"]["extractor_config"]
    assert body["url_variant_key"] is None
    # ...whereas typing the pinned offer's own price labels it.
    body = post(client, {"url": "https://x.test/p?sku=A-S", "price_text": "100"})
    assert body["source"]["extractor_config"]["variant_key"] == "s|red"
    assert body["url_variant_key"] == "s|red"


def test_registry_extract_reports_the_url_variant(
    client: TestClient, fetcher: FakeFetcher, normalized: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetcher.result = FetchResult("ok", VUORI_URL, 200, fixture(VUORI_FILE))
    monkeypatch.setattr(extract_base, "extract", lambda html, url: [
        Extracted(6400, "USD", False, "xxs|black", "jsonld"),
        Extracted(6400, "USD", True, "xs|black", "jsonld"),
    ])
    assert post(client, {"url": f"{VUORI_URL}?objectId=41437918036071"})["url_variant_key"] == "xs|black"
    assert post(client, {"url": VUORI_URL})["url_variant_key"] is None


def test_registry_url_variant_must_be_one_the_extractor_returns(
    client: TestClient, fetcher: FakeFetcher, normalized: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetcher.result = FetchResult("ok", VUORI_URL, 200, fixture(VUORI_FILE))
    monkeypatch.setattr(extract_base, "extract", lambda html, url: [Extracted(6400, "USD", True, "l|black", "jsonld")])
    assert post(client, {"url": f"{VUORI_URL}?objectId=41437918036071"})["url_variant_key"] is None


def test_price_text_not_found(client: TestClient, fetcher: FakeFetcher, normalized: None) -> None:
    fetcher.result = page("fixture-farmrio-com-products-rustic-flowers-winter-white-sleeveless-.html")
    body = post(client, {"url": FARMRIO_URL, "price_text": "$297.00"})
    assert body["status"] == "price_text_not_found"
    assert body["message"] == (
        "We couldn't find $297.00 on that page. The retailer may load prices with JavaScript, which we can't read yet.")
    assert body["source"]["title"]


def test_price_text_unparseable_skips_the_fetch(client: TestClient, fetcher: FakeFetcher, normalized: None) -> None:
    body = post(client, {"url": FARMRIO_URL, "price_text": "298,00"})
    assert body["status"] == "price_text_unparseable"
    assert body["source"]["url_hash"] == "hash-123"
    assert fetcher.urls == []


def test_blank_price_text_is_ignored(client: TestClient, normalized: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_base, "extract", lambda html, url: [])
    assert post(client, {"url": FARMRIO_URL, "price_text": "  "})["status"] == "no_price"


def test_price_text_on_vuori_next_data_only_page(client: TestClient, fetcher: FakeFetcher, normalized: None) -> None:
    # Strip JSON-LD so only __NEXT_DATA__ can match.
    html = fixture("fixture-vuoriclothing-com-products-womens-daily-piped-bra-black-refS.html")
    html = html.replace('type="application/ld+json"', 'type="text/disabled"')
    fetcher.result = FetchResult("ok", "https://vuoriclothing.com/products/x", 200, html)
    body = post(client, {"url": "https://vuoriclothing.com/products/x", "price_text": "64"})
    assert body["status"] == "ok"
    assert body["source"]["extractor"] == "nextdata"
    assert body["source"]["extractor_config"]["blob"] == "nextdata"
    assert body["variants"][0]["price_cents"] == 6400


# ---------------------------------------------------------------- helpers

@pytest.mark.parametrize(
    "url, retailer",
    [("https://www.Farmrio.com/x", "farmrio.com"), ("https://shop.lululemon.com/p", "lululemon.com"),
     ("https://vuoriclothing.com/p", "vuoriclothing.com")],
)
def test_retailer_of(url: str, retailer: str) -> None:
    assert retailer_of(url) == retailer


def test_extractor_kind() -> None:
    assert extractor_kind("nextdata:vuori") == "nextdata"
    assert extractor_kind("jsonld") == "jsonld"
    assert extractor_kind("shopify-json") == "jsonld"
