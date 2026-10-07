"""HTTP API for the Next.js app. The contract is docs/worker-api.md.

POST /extract fetches a page once and reports what we can read. It writes
nothing: the app saves the source through RLS, and the scheduler's first
check records the first price point.
"""

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from config import API_REQUIRED, Settings, load_settings
from db import split_variant_key
from extract import base as extract_base
from extract import learned
from extract import normalize
from extract.base import Extracted
from extract.findpath import Candidate, find_paths, parse_price_text
from extract.urlvariant import PinnedVariant, find_pinned_variant
from extract.meta import page_meta
from fetcher import Fetcher, FetchResult
from logs import setup_logging, warn_once
from notify import money
from scheduler import is_valid

log = logging.getLogger("api")

Status = Literal[
    "ok", "no_price", "not_implemented", "blocked", "fetch_failed",
    "invalid_url", "price_text_unparseable", "price_text_not_found",
]
ExtractorKind = Literal["jsonld", "nextdata", "microdata", "css", "manual"]
_KINDS = ("jsonld", "nextdata", "microdata", "css", "manual")


class ExtractRequest(BaseModel):
    url: str
    price_text: str | None = None


class SourceOut(BaseModel):
    canonical_url: str
    url_hash: str
    retailer: str
    title: str | None = None
    image_url: str | None = None
    extractor: ExtractorKind = "jsonld"
    extractor_config: dict[str, Any] = {}
    needs_browser: bool = False


class VariantOut(BaseModel):
    variant_key: str
    size: str | None
    color: str | None
    price_cents: int
    currency: str
    in_stock: bool


class ExtractResponse(BaseModel):
    status: Status
    message: str
    source: SourceOut | None
    variants: list[VariantOut] = []
    # Normalized key of the variant the pasted URL points at; null unless it
    # pins exactly one variant that `variants` can be watched by.
    url_variant_key: str | None = None


# -------------------------------------------------------------- copy

MSG_INVALID_URL = "That doesn't look like a product link. Paste the full address, starting with https://."
MSG_NORMALIZE_STUB = (
    "We can't add links yet because link cleanup isn't built. Try again after the next worker update."
)
MSG_EXTRACT_STUB = (
    "Automatic price reading isn't built yet. Enter the price you see on the page and we'll find it."
)
MSG_BLOCKED = (
    "The retailer blocked our request (bot protection). You can keep watching it, "
    "but we can't check its price yet."
)
MSG_NO_PRICE = (
    "The page loaded but no price was found. Enter the price you see on the page and we'll find it."
)


def msg_fetch_failed(result: FetchResult) -> str:
    detail = f" ({result.error})" if result.error else ""
    return f"We couldn't load that page{detail}. Check the link and try again."


def msg_unparseable(text: str) -> str:
    return f"We couldn't read “{text.strip()[:40]}” as a price. Enter it as shown on the page, like $298.00."


def msg_not_found(cents: int) -> str:
    return (
        f"We couldn't find {money(cents)} on that page. The retailer may load prices "
        "with JavaScript, which we can't read yet."
    )


def msg_ok(variants: list[VariantOut], learned_path: bool) -> str:
    prices = sorted(v.price_cents for v in variants)
    currency = variants[0].currency
    if learned_path:
        return f"Found {money(prices[0], currency)} on the page. We'll check that spot for changes."
    if len(variants) == 1:
        return f"Found {money(prices[0], currency)}. Check it matches the page before you save."
    span = (money(prices[0], currency) if prices[0] == prices[-1]
            else f"{money(prices[0], currency)} to {money(prices[-1], currency)}")
    return f"Found {len(variants)} variants at {span}. Check they match the page before you save."


# ------------------------------------------------------------ helpers

def retailer_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    for prefix in ("www.", "shop."):
        if host.startswith(prefix):
            return host[len(prefix):]
    return host


def extractor_kind(strategy: str) -> ExtractorKind:
    """Map Extracted.strategy ("jsonld", "nextdata:vuori", …) onto the DB enum."""
    head = strategy.split(":", 1)[0]
    return head if head in _KINDS else "jsonld"  # type: ignore[return-value]


def variant_out(e: Extracted) -> VariantOut:
    key, size, color = split_variant_key(e.variant_key)
    return VariantOut(variant_key=key, size=size, color=color, price_cents=e.price_cents,
                      currency=e.currency.strip().upper(), in_stock=e.in_stock)


def _is_http_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


# ------------------------------------------------------------- the flow

async def run_extract(req: ExtractRequest, fetcher: Fetcher) -> ExtractResponse:
    url = req.url.strip()
    if not _is_http_url(url):
        return ExtractResponse(status="invalid_url", message=MSG_INVALID_URL, source=None)

    try:
        canonical_url, url_hash = normalize.normalize_url(url)
    except NotImplementedError:
        warn_once(log, "normalize_url", "extract.normalize.normalize_url() is not implemented yet.")
        return ExtractResponse(status="not_implemented", message=MSG_NORMALIZE_STUB, source=None)
    except ValueError:
        return ExtractResponse(status="invalid_url", message=MSG_INVALID_URL, source=None)

    source = SourceOut(canonical_url=canonical_url, url_hash=url_hash, retailer=retailer_of(canonical_url))

    # Parse before fetching: a typo shouldn't cost a request to the retailer.
    target: int | None = None
    if req.price_text is not None and req.price_text.strip():
        target = parse_price_text(req.price_text)
        if target is None:
            return ExtractResponse(status="price_text_unparseable",
                                   message=msg_unparseable(req.price_text), source=source)

    result = await fetcher.fetch(canonical_url)
    if result.kind == "blocked":
        return ExtractResponse(status="blocked", message=MSG_BLOCKED, source=source)
    if not result.ok:
        return ExtractResponse(status="fetch_failed", message=msg_fetch_failed(result), source=source)

    html = result.html
    meta = await asyncio.to_thread(page_meta, html, result.url)
    source = source.model_copy(update={"title": meta.title, "image_url": meta.image_url})

    if target is not None:
        return await _teach(html, target, source, url)

    try:
        found = await asyncio.to_thread(extract_base.extract, html, canonical_url)
    except NotImplementedError:
        warn_once(log, "extract.extract", "extract.base.extract() is not implemented yet.")
        return ExtractResponse(status="not_implemented", message=MSG_EXTRACT_STUB, source=source)
    except Exception:
        log.exception("extract() crashed on %s", canonical_url)
        found = []

    valid = [e for e in found if is_valid(e)]
    if not valid:
        return ExtractResponse(status="no_price", message=MSG_NO_PRICE, source=source)
    variants = [variant_out(e) for e in valid]
    source = source.model_copy(update={"extractor": extractor_kind(valid[0].strategy)})
    # Only report the URL's variant if the extractor's own keys include it, so
    # watching it can actually fire.
    pinned = await asyncio.to_thread(find_pinned_variant, html, url)
    url_key = pinned.key if pinned and pinned.key in {v.variant_key for v in variants} else None
    return ExtractResponse(status="ok", message=msg_ok(variants, False), source=source,
                           variants=variants, url_variant_key=url_key)


def _pinned_config(c: Candidate, pinned: PinnedVariant | None) -> dict[str, Any]:
    """The learned config for `c`, with the variant stored if `c` lies inside the pinned offer."""
    cfg = c.config()
    if not pinned:
        return cfg
    inside = [ids for loc, ids in zip(pinned.locations, pinned.ids) if c.within(loc)]
    if not inside:
        return cfg
    if pinned.key:
        cfg.update(variant_key=pinned.key, size=pinned.size, color=pinned.color)
    # Index paths like offers[2] would silently read another variant if the
    # retailer reorders offers; remember the offer's ids so resolve() can refuse.
    pin_ids = sorted(set().union(*inside))
    if pin_ids:
        cfg["pin_ids"] = pin_ids
    return cfg


async def _teach(html: str, target: int, source: SourceOut, url: str) -> ExtractResponse:
    """Find the user's price in the page's JSON and confirm the learned path reads it back.

    If the pasted URL points at one offer (`?variant=…`), paths inside that
    offer win, and the config remembers the offer's variant key.
    """
    pinned = await asyncio.to_thread(find_pinned_variant, html, url)
    candidates = await asyncio.to_thread(
        find_paths, html, target, pinned.locations if pinned else ())
    for c in candidates:
        cfg = _pinned_config(c, pinned)
        got = learned.resolve(html, cfg)
        if got and got[0].price_cents == target:
            variants = [variant_out(got[0])]
            source = source.model_copy(update={"extractor": c.blob, "extractor_config": cfg})
            return ExtractResponse(status="ok", message=msg_ok(variants, True), source=source,
                                   variants=variants, url_variant_key=cfg.get("variant_key"))
    return ExtractResponse(status="price_text_not_found", message=msg_not_found(target), source=source)


# --------------------------------------------------------------- the app

def require_bearer(request: Request) -> None:
    secret: str = request.app.state.settings.worker_shared_secret
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    # compare_digest on bytes: constant-time, and safe for non-ASCII input.
    if not (
        secret
        and scheme.lower() == "bearer"
        and hmac.compare_digest(token.strip().encode(), secret.encode())
    ):
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Bearer"})


def create_app(settings: Settings | None = None, fetcher: Fetcher | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Loaded here rather than at import so `import api` works without
        # env vars; uvicorn still refuses to start if they're missing.
        if settings is None:
            setup_logging()
        app.state.settings = settings or load_settings(API_REQUIRED)
        s = app.state.settings
        app.state.fetcher = fetcher or Fetcher(
            min_delay_s=s.domain_delay_s, jitter_s=s.domain_jitter_s, timeout_s=s.fetch_timeout_s
        )
        try:
            yield
        finally:
            if fetcher is None:
                await app.state.fetcher.aclose()

    app = FastAPI(title="Watchlist worker", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/extract", response_model=ExtractResponse, dependencies=[Depends(require_bearer)])
    async def extract_route(body: ExtractRequest, request: Request) -> ExtractResponse:
        return await run_extract(body, request.app.state.fetcher)

    return app


app = create_app()
