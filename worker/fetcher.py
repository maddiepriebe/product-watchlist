"""Polite page fetching.

One request at a time per domain, with a jittered minimum gap between
requests to the same domain, so a batch of 20 Farm Rio URLs trickles out
instead of arriving as a burst that trips bot protection. Different domains
proceed concurrently.
"""

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal
from urllib.parse import urlsplit

import httpx

# A real desktop browser's headers. Retailers' bot protection rejects
# obvious library UAs outright (see scripts/spike.py).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Product pages run 0.5–1 MB; anything far beyond that isn't a product page.
MAX_BYTES = 8 * 1024 * 1024

FetchKind = Literal["ok", "blocked", "http_error", "network_error"]


@dataclass(frozen=True)
class FetchResult:
    kind: FetchKind
    url: str                     # final URL after redirects
    status_code: int | None = None
    html: str = ""
    error: str | None = None     # short, log-friendly detail

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


def domain_of(url: str) -> str:
    """The politeness key: lowercased host without a leading "www."."""
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def looks_blocked(status_code: int, html: str) -> bool:
    """403, or Akamai's 200/4xx "Access Denied" interstitial."""
    if status_code == 403:
        return True
    head = html[:4096].lower()
    return "<title>access denied" in head


class Fetcher:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        min_delay_s: float = 2.0,
        jitter_s: float = 1.5,
        timeout_s: float = 20.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            headers=HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(timeout_s, connect=10.0),
        )
        self._min_delay_s = min_delay_s
        self._jitter_s = jitter_s
        self._sleep = sleep
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_done: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> FetchResult:
        domain = domain_of(url)
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            last = self._last_done.get(domain)
            if last is not None:
                gap = self._min_delay_s + random.uniform(0, self._jitter_s)
                wait = last + gap - self._clock()
                if wait > 0:
                    await self._sleep(wait)
            try:
                return await self._get(url)
            finally:
                # Measured from when the request finished, so a slow page
                # doesn't eat into the gap before the next one.
                self._last_done[domain] = self._clock()

    async def _get(self, url: str) -> FetchResult:
        try:
            async with self._client.stream("GET", url, headers=HEADERS) as resp:
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        return FetchResult(
                            "http_error", str(resp.url), resp.status_code,
                            error=f"response larger than {MAX_BYTES} bytes",
                        )
                encoding = resp.encoding or "utf-8"
                html = bytes(body).decode(encoding, errors="replace")
                final_url = str(resp.url)
                status = resp.status_code
        except httpx.TimeoutException:
            return FetchResult("network_error", url, error="timed out")
        except httpx.HTTPError as e:
            return FetchResult("network_error", url, error=f"{type(e).__name__}: {e}")

        if looks_blocked(status, html):
            return FetchResult("blocked", final_url, status, html, error=f"HTTP {status}")
        if not 200 <= status < 300:
            return FetchResult("http_error", final_url, status, error=f"HTTP {status}")
        return FetchResult("ok", final_url, status, html)
