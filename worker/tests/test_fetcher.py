import asyncio
from pathlib import Path

import httpx

from fetcher import HEADERS, Fetcher, domain_of

FIXTURES = Path(__file__).parent / "fixtures"


def make_fetcher(handler, **kw) -> Fetcher:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    return Fetcher(client, min_delay_s=kw.pop("min_delay_s", 0.0), jitter_s=0.0, **kw)


class Tracker:
    """Records how many requests per host are in flight at once."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.active: dict[str, int] = {}
        self.max_active: dict[str, int] = {}
        self.max_total = 0
        self.seen_headers: list[httpx.Headers] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.seen_headers.append(request.headers)
        self.active[host] = self.active.get(host, 0) + 1
        self.max_active[host] = max(self.max_active.get(host, 0), self.active[host])
        self.max_total = max(self.max_total, sum(self.active.values()))
        await asyncio.sleep(self.delay)
        self.active[host] -= 1
        return httpx.Response(200, text="<html>ok</html>")


async def test_same_domain_requests_never_overlap() -> None:
    t = Tracker()
    f = make_fetcher(t.handler)
    urls = [f"https://farmrio.com/products/{i}" for i in range(4)]
    # www. and bare host share a politeness slot.
    urls.append("https://www.farmrio.com/products/x")
    results = await asyncio.gather(*(f.fetch(u) for u in urls))
    assert all(r.ok for r in results)
    assert t.max_active["farmrio.com"] == 1
    assert t.max_active.get("www.farmrio.com", 1) == 1
    assert t.max_total == 1


async def test_different_domains_run_concurrently() -> None:
    t = Tracker(delay=0.1)
    f = make_fetcher(t.handler)
    urls = ["https://farmrio.com/a", "https://vuoriclothing.com/b", "https://tracksmith.com/c"]
    await asyncio.gather(*(f.fetch(u) for u in urls))
    assert t.max_total == 3


async def test_waits_min_delay_between_same_domain_requests() -> None:
    sleeps: list[float] = []
    now = [100.0]

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)
        now[0] += s

    f = make_fetcher(
        lambda r: httpx.Response(200, text="ok"),
        min_delay_s=2.0, sleep=fake_sleep, clock=lambda: now[0],
    )
    await f.fetch("https://farmrio.com/a")
    await f.fetch("https://farmrio.com/b")
    await f.fetch("https://tracksmith.com/c")   # different domain: no wait
    assert sleeps == [2.0]


async def test_sends_browser_headers() -> None:
    t = Tracker(delay=0)
    f = make_fetcher(t.handler)
    await f.fetch("https://farmrio.com/a")
    assert t.seen_headers[0]["user-agent"] == HEADERS["User-Agent"]
    assert "text/html" in t.seen_headers[0]["accept"]


async def test_403_is_blocked() -> None:
    f = make_fetcher(lambda r: httpx.Response(403, text="nope"))
    r = await f.fetch("https://shop.lululemon.com/p/x")
    assert r.kind == "blocked"
    assert r.status_code == 403


async def test_akamai_access_denied_page_is_blocked_even_on_200() -> None:
    html = (FIXTURES / "fixture-shop-lululemon-com-p-women-shorts-Speed-Up-High-Rise-Short-4.html").read_text()
    f = make_fetcher(lambda r: httpx.Response(200, text=html))
    r = await f.fetch("https://shop.lululemon.com/p/x")
    assert r.kind == "blocked"


async def test_other_non_2xx_is_http_error() -> None:
    f = make_fetcher(lambda r: httpx.Response(404, text="gone"))
    r = await f.fetch("https://farmrio.com/missing")
    assert r.kind == "http_error"
    assert r.status_code == 404
    assert r.html == ""


async def test_network_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    f = make_fetcher(boom)
    r = await f.fetch("https://farmrio.com/a")
    assert r.kind == "network_error"
    assert "ConnectError" in (r.error or "")


async def test_timeout_is_network_error() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    f = make_fetcher(slow)
    r = await f.fetch("https://farmrio.com/a")
    assert r.kind == "network_error"
    assert r.error == "timed out"


async def test_follows_redirects_and_reports_final_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "https://farmrio.com/new"})
        return httpx.Response(200, text="<html>new</html>")

    f = make_fetcher(handler)
    r = await f.fetch("https://farmrio.com/old")
    assert r.ok
    assert r.url == "https://farmrio.com/new"


def test_domain_of() -> None:
    assert domain_of("https://WWW.Farmrio.com/x?y=1") == "farmrio.com"
    assert domain_of("https://shop.lululemon.com/p") == "shop.lululemon.com"
