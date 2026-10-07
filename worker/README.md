# Worker

Fetches product pages, reads prices, records price points, and sends alert
emails. Runs on Fly.io as two process groups from one image:

- **web**: `uvicorn api:app`, the HTTP API the Next.js app calls when a user
  adds a product. Contract: [`docs/worker-api.md`](../docs/worker-api.md).
- **scheduler**: `python -m scheduler`, the polling loop that checks due
  sources and sends alerts.

Prices are integer cents everywhere. JSON is parsed with `Decimal`, so no float
touches a price, and nothing is saved unless it was read exactly.

## Modules

| File | What it does |
| --- | --- |
| `config.py` | Reads env vars. Each process fails at startup, listing every missing var. |
| `logs.py` | Logging setup, plus `warn_once` so a stub reports itself once, not once per source. |
| `fetcher.py` | Async httpx with browser headers. One request at a time per domain, with a jittered gap between them. Results are `ok`, `blocked` (403 or Akamai "Access Denied"), `http_error` or `network_error`. |
| `extract/base.py` | `extract(html, url)`, the per-retailer extractor registry. **Owner-implemented stub.** |
| `extract/normalize.py` | `normalize_url(url)`, which returns the canonical URL and hash. **Owner-implemented stub.** |
| `extract/findpath.py` | The "teach the extractor" search. `parse_price_text` turns "$1,298.50" into 129850 and rejects anything ambiguous; `find_paths` finds JSON-LD / `__NEXT_DATA__` paths whose value equals that price. Only price-named keys can match, so a size is never picked. |
| `extract/learned.py` | Reads a price through a learned `extractor_config`. Returns `[]` when the path no longer leads to an exact number. |
| `extract/meta.py` | Title and image for display (JSON-LD name, og:title, og:image). Never prices. |
| `db.py` | Every SQL query. Claims due sources with `FOR UPDATE SKIP LOCKED` plus a lease, upserts variants, writes price points, counts failures, loads watches and notifications. |
| `alerts.py` | `evaluate(watch, latest, history)`, which decides which alerts fire. **Owner-implemented stub.** |
| `notify.py` | After a price point is written, evaluates each email watch on that variant, logs a `notifications` row, then sends the email through Resend. |
| `scheduler.py` | The loop: claim, fetch, extract, record, alert. Delta logging, failure counting, rescheduling. |
| `api.py` | FastAPI: `POST /extract` (bearer auth) and `GET /healthz`. |
| `models.py` | Plain dataclasses shared with `alerts.py`. |

### How a check works

1. `db.claim_due_sources` takes up to `WORKER_BATCH_SIZE` sources whose status
   is `active` or `failing` and whose `next_check_at` has passed, and pushes
   `next_check_at` out by `WORKER_LEASE_MINS`. That lease stops parallel
   workers from fetching the same source. If a worker dies mid-check, the
   source comes back when the lease runs out.
2. Fetch, then extract. Sources with `extractor_config.learned = true` read
   their learned path; all others call `extract()`.
3. A price point is written only when the price, stock or currency changed,
   or when the last point is more than 24h old (the heartbeat).
4. On success the source becomes `active`, failures reset, and the next check
   is `check_interval_mins` ±10% away. On failure `consecutive_failures` goes
   up, and at 3 the source flips to `failing`. Paused or unsupported sources
   are never touched.
5. While `extract()` is still a stub, a check logs once, writes a note to
   `last_error`, and reschedules without counting a failure.
6. For each point written, `notify.dispatch_alerts` runs `alerts.evaluate`
   for each matching email watch, then logs and sends each alert. A failed
   send is stored on the notification row and never stops the loop.

## Local development

Requires [uv](https://docs.astral.sh/uv/). From `worker/`:

```bash
uv sync                                   # create .venv with dev deps
cp .env.example .env                      # fill in real values
uv run --env-file .env uvicorn api:app --reload --port 8080
uv run --env-file .env python -m scheduler
```

To try the API:

```bash
curl -s localhost:8080/healthz
curl -s localhost:8080/extract \
  -H "Authorization: Bearer $WORKER_SHARED_SECRET" -H 'Content-Type: application/json' \
  -d '{"url": "https://farmrio.com/products/…", "price_text": "$298.00"}'
```

Only the dependencies in `pyproject.toml` are approved. Ask before you add one.

## Tests

```bash
uv run pytest -q
```

DB integration tests (`test_db.py`, plus parts of `test_scheduler.py` and
`test_notify.py`) skip unless `TEST_DATABASE_URL` points at a Postgres 15+
server where the tests can create and drop databases. Each test builds a fresh
database from the Supabase shim plus `supabase/migrations/*.sql`, then drops it.

```bash
# throwaway server (initdb refuses to run as root; on Linux run these as the postgres user)
initdb -D /var/tmp/wl-pg/data -U postgres --auth=trust
pg_ctl -D /var/tmp/wl-pg/data -o "-p 55450 -c listen_addresses=127.0.0.1" -w start

TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55450/postgres uv run pytest -q
```

On Linux as root, put the `initdb` and `pg_ctl` lines in a script owned by
`postgres` and run it with `su postgres -s /path/to/script`. The binaries are
in `/usr/lib/postgresql/16/bin`.

`tests/pgtest.py` has the DB fixtures and `tests/fakes.py` has in-memory
stand-ins for the DB and the email sender. They aren't in `conftest.py`
because that file belongs to the stub tests.

## Deploy to Fly.io

```bash
cd worker
fly launch --no-deploy            # keep fly.toml; pick an app name and a region near Supabase
fly secrets set \
  DATABASE_URL='postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres' \
  WORKER_SHARED_SECRET="$(openssl rand -hex 32)" \
  RESEND_API_KEY=re_… \
  ALERT_FROM_EMAIL='Watchlist <alerts@yourdomain.com>' \
  APP_URL=https://<app>.vercel.app
fly deploy
fly scale count web=1 scheduler=1
```

Then give the Next.js app (Vercel) `WORKER_URL=https://<fly-app>.fly.dev` and
the same `WORKER_SHARED_SECRET`.

**Which Supabase connection string:** Project Settings → Database → Connection
string. Use the **Session pooler** (port **5432**) or the direct connection.
The scheduler holds long-lived connections, so don't use the transaction pooler
on port 6543. The direct connection is IPv6-only unless you buy the IPv4
add-on; Fly supports IPv6, but the session pooler works everywhere. This
string connects as `postgres`, which bypasses RLS, so it belongs only in the
worker's secrets.

Running more than one scheduler machine is safe because claims are leased,
but per-domain pacing only works inside one process. Two schedulers, or the
scheduler and `web`, can hit the same retailer at the same moment. One machine
of each is the right size for now.
