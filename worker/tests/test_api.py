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
    assert body == {"status": "invalid_url", "message": body["message"], "source": None, "variants": []}
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
        "learned": True, "blob": "jsonld", "block": 1, "path": ["offers", 0, "price"], "unit": "major"}
    assert body["variants"] == [
        {"variant_key": "", "size": None, "color": None, "price_cents": 29800, "currency": "USD", "in_stock": True}]
    # what the app stores is what the scheduler will read back
    assert resolve(fetcher.result.html, src["extractor_config"])[0].price_cents == 29800


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
