"""Alert dispatch: decide (alerts.evaluate), log (notifications), email (Resend).

Runs after the scheduler writes a price point. Every failure here is logged
and contained: a broken email must never stop prices being recorded.
"""

import asyncio
import html as htmllib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

import resend

import alerts
from db import Database, SourceRow, WatchRow, split_variant_key
from logs import warn_once
from models import AlertReason, PricePoint

log = logging.getLogger(__name__)

_SYMBOLS = {"USD": "$", "CAD": "CA$", "AUD": "A$", "GBP": "£", "EUR": "€"}


def money(cents: int, currency: str = "USD") -> str:
    """29800 -> "$298.00". Integer math only, like lib/format.ts."""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    symbol = _SYMBOLS.get(currency.upper())
    amount = f"{whole:,}.{frac:02d}"
    return f"{sign}{symbol}{amount}" if symbol else f"{sign}{amount} {currency.upper()}"


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


class EmailSender(Protocol):
    async def send(self, *, to: str, email: Email, idempotency_key: str) -> None:
        """Raise on failure."""
        ...


class ResendSender:
    def __init__(self, api_key: str, from_email: str) -> None:
        resend.api_key = api_key
        self._from = from_email

    async def send(self, *, to: str, email: Email, idempotency_key: str) -> None:
        params: resend.Emails.SendParams = {
            "from": self._from,
            "to": [to],
            "subject": email.subject,
            "text": email.text,
            "html": email.html,
        }
        # The SDK is synchronous; keep it off the event loop.
        await asyncio.to_thread(
            resend.Emails.send, params, {"idempotency_key": idempotency_key}
        )


# ------------------------------------------------------------------ copy

def variant_label(variant_key: str) -> str | None:
    _, size, color = split_variant_key(variant_key)
    parts = [p for p in (size, color) if p]
    return ", ".join(parts) or None


def median_cents(points: list[PricePoint]) -> Decimal | None:
    prices = sorted(p.price_cents for p in points)
    if not prices:
        return None
    mid = len(prices) // 2
    if len(prices) % 2:
        return Decimal(prices[mid])
    return (Decimal(prices[mid - 1]) + Decimal(prices[mid])) / 2


def _pct(value: Decimal) -> str:
    """Decimal("15.00") -> "15", Decimal("12.50") -> "12.5"."""
    return f"{value.normalize():f}"


def reason_line(
    reason: AlertReason, watch: WatchRow, latest: PricePoint,
    history: list[PricePoint], variant_key: str,
) -> str:
    if reason == "below_threshold":
        if watch.alert_below_cents is not None:
            return f"Below your {money(watch.alert_below_cents, latest.currency)} alert."
        return "Below your price alert."
    if reason == "pct_drop":
        window_start = latest.observed_at - timedelta(days=30)
        median = median_cents([p for p in history if p.observed_at >= window_start])
        if median:
            pct = ((median - latest.price_cents) / median * 100).quantize(Decimal(1), ROUND_HALF_UP)
            if pct > 0:
                return f"{pct}% under its 30-day typical price."
        if watch.alert_pct_drop is not None:
            return f"At least {_pct(Decimal(watch.alert_pct_drop))}% under its 30-day typical price."
        return "Well under its 30-day typical price."
    if reason == "new_low":
        return "Lowest price in 90 days."
    label = variant_label(variant_key)
    return f"Back in stock in {label}." if label else "Back in stock."


def compose(
    reason: AlertReason, *, watch: WatchRow, source: SourceRow, variant_key: str,
    latest: PricePoint, history: list[PricePoint], app_url: str,
) -> Email:
    title = watch.nickname or source.title or f"Your item at {source.retailer}"
    price = money(latest.price_cents, latest.currency)
    label = variant_label(variant_key)
    if reason == "back_in_stock":
        subject = f"{title} is back in stock" + (f" in {label}" if label else "")
        lead = f"{title} is back in stock at {source.retailer} for {price}."
    else:
        subject = f"{title} dropped to {price}"
        lead = f"{title} dropped to {price} at {source.retailer}."
    why = reason_line(reason, watch, latest, history, variant_key)
    watchlist = f"{app_url}/watchlist"
    footer = "You get this email because you watch this item. Change or mute alerts on your watchlist."

    text = (
        f"{lead}\n{why}\n\n"
        f"View it on {source.retailer}: {source.canonical_url}\n"
        f"Your watchlist: {watchlist}\n\n"
        f"{footer}\n"
    )
    e = htmllib.escape
    body = (
        f"<p style=\"font-size:16px\"><strong>{e(lead)}</strong></p>"
        f"<p>{e(why)}</p>"
        f"<p><a href=\"{e(source.canonical_url)}\">View it on {e(source.retailer)}</a>"
        f" &middot; <a href=\"{e(watchlist)}\">Your watchlist</a></p>"
        f"<p style=\"color:#666;font-size:12px\">{e(footer)}</p>"
    )
    page = (
        "<!doctype html><html><body style=\"font-family:-apple-system,Segoe UI,Helvetica,Arial,"
        f"sans-serif;color:#111;line-height:1.5\">{body}</body></html>"
    )
    return Email(subject=subject, text=text, html=page)


# --------------------------------------------------------------- dispatch

async def dispatch_alerts(
    db: Database, sender: EmailSender, *, app_url: str,
    source: SourceRow, variant_id: str, variant_key: str, latest: PricePoint,
) -> int:
    """Evaluate every email watch on this variant and send what fires. Returns emails sent."""
    async with db.transaction() as q:
        watches = [w for w in await q.watches_for_variant(source.id, variant_key) if w.channel == "email"]
        if not watches:
            return 0
        history = await q.history(variant_id, before=latest.observed_at)
        since = latest.observed_at - timedelta(days=90)
        recent = {w.id: await q.recent_alerts(w.id, since) for w in watches}

    sent = 0
    for watch in watches:
        try:
            reasons = alerts.evaluate(watch.to_model(recent[watch.id]), latest, history)
        except NotImplementedError:
            warn_once(log, "alerts.evaluate", "alerts.evaluate() is not implemented yet; no alerts will be sent.")
            return sent
        except Exception:
            log.exception("alerts.evaluate failed for watch %s", watch.id)
            continue
        if not reasons:
            continue
        try:
            sent += await _send(db, sender, app_url=app_url, watch=watch, source=source,
                                variant_id=variant_id, variant_key=variant_key,
                                latest=latest, history=history, reasons=reasons)
        except Exception:
            log.exception("alert dispatch failed for watch %s", watch.id)
    return sent


async def _send(
    db: Database, sender: EmailSender, *, app_url: str, watch: WatchRow, source: SourceRow,
    variant_id: str, variant_key: str, latest: PricePoint, history: list[PricePoint],
    reasons: list[AlertReason],
) -> int:
    async with db.transaction() as q:
        to = await q.user_email(watch.user_id)
    if not to:
        log.warning("watch %s: owner has no email address; skipping %s", watch.id, reasons)
        return 0

    sent = 0
    for reason in reasons:
        # Log first, then send: if we crash mid-send, the row (delivered =
        # false) records the attempt instead of the alert vanishing.
        async with db.transaction() as q:
            nid = await q.insert_notification(
                watch_id=watch.id, source_id=source.id, variant_id=variant_id,
                reason=reason, price_cents=latest.price_cents, sent_at=datetime.now(UTC),
            )
        email = compose(reason, watch=watch, source=source, variant_key=variant_key,
                        latest=latest, history=history, app_url=app_url)
        error: str | None = None
        try:
            await sender.send(to=to, email=email, idempotency_key=f"notification-{nid}")
        except Exception as e:
            error = f"{type(e).__name__}: {e}"[:500]
            log.warning("email for notification %s failed: %s", nid, error)
        async with db.transaction() as q:
            await q.mark_notification(nid, delivered=error is None, error=error)
        sent += error is None
    return sent
