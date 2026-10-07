# Worker HTTP API

The Next.js app never scrapes. To detect a price for the add-product flow it
calls the worker, server-side only (Server Actions / Route Handlers).

## `POST /extract`

Fetches the page once and reports what the worker can read from it. **It
writes nothing to the database.** The app saves the source/watch itself
through RLS, and the scheduler's first check writes the first price point.

Headers

```
Authorization: Bearer $WORKER_SHARED_SECRET
Content-Type: application/json
```

Body

```jsonc
{
  "url": "https://…",          // required, as pasted
  "price_text": "$298.00"      // optional — the manual fallback: the price the user sees
}
```

Response `200` (every outcome that isn't an auth/body error):

```jsonc
{
  "status": "ok",              // see table below
  "message": "…",              // user-facing copy, sentence case, says what to do
  "source": {                  // null when the URL couldn't be normalized
    "canonical_url": "https://farmrio.com/products/…?variant=44352681902173",
    "url_hash": "…",
    "retailer": "farmrio.com",
    "title": "Rustic Flowers Winter White Sleeveless Maxi Dress",   // or null
    "image_url": "https://…",                                       // or null
    "extractor": "jsonld",     // extractor_kind enum
    "extractor_config": {},    // {} for registry extractors; a learned path for manual
    "needs_browser": false
  },
  "variants": [                // non-empty only when status = "ok"
    {
      "variant_key": "M|black", // "" for single-variant products
      "size": "M",              // or null
      "color": "black",         // or null
      "price_cents": 29800,
      "currency": "USD",
      "in_stock": true
    }
  ]
}
```

| `status`                | Meaning                                                    | App does                         |
| ----------------------- | ---------------------------------------------------------- | -------------------------------- |
| `ok`                    | Price(s) read with an explicit path.                       | Show for confirmation.           |
| `no_price`              | Page loaded; no price found.                               | Offer manual fallback.           |
| `not_implemented`       | `normalize_url` or `extract` is still a stub.              | Offer manual fallback if `source` is set; else show message. |
| `blocked`               | 403 / bot protection.                                      | Offer "keep watching anyway" (saved as `unsupported`). |
| `fetch_failed`          | Network error, timeout, non-2xx other than 403.            | Show message, let user retry.    |
| `invalid_url`           | Not an http(s) URL.                                        | Show message.                    |
| `price_text_unparseable`| `price_text` isn't a price we can parse exactly.           | Ask again.                       |
| `price_text_not_found`  | `price_text` parsed, but no JSON value on the page equals it. | Offer "keep watching anyway" (saved as `unsupported`). |

`401` — missing/wrong bearer token. `422` — malformed body.

### Manual fallback ("teach the extractor")

With `price_text`, the worker parses it to cents (exactly — `"$1,298.50"` →
`129850`; anything ambiguous is `price_text_unparseable`), then searches the
page's JSON-LD blocks and embedded state (`__NEXT_DATA__`) for a value equal to
it. A match becomes the source's learned extractor:

```jsonc
"extractor": "nextdata",          // or "jsonld"
"extractor_config": {
  "learned": true,
  "blob": "nextdata",             // "jsonld" | "nextdata"
  "block": 0,                     // which JSON-LD <script>, 0-based (jsonld only)
  "path": ["props", "pageProps", "product", "price"],   // keys and list indices
  "unit": "major"                 // "major" (298.00) or "minor" (29800)
}
```

The scheduler uses `extractor_config.path` when `learned` is true and the
registry `extract()` otherwise. Nothing is saved from the user's text alone.

## `GET /healthz`

`200 {"ok": true}`. No auth.

## Environment

| Var                     | Used by        |
| ----------------------- | -------------- |
| `WORKER_URL`            | Next.js (server only) |
| `WORKER_SHARED_SECRET`  | both           |
| `DATABASE_URL`          | worker — Supabase Postgres connection string (bypasses RLS; worker-only) |
| `RESEND_API_KEY`        | worker         |
| `ALERT_FROM_EMAIL`      | worker         |
| `APP_URL`               | worker — links in alert emails |
