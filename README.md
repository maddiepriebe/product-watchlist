# Product Watchlist

Multi-user price tracking. Users watch products; when a price drops or a
sold-out size returns, they get an email.

**Stack:** Next.js (App Router, TS, Tailwind) on Vercel · Supabase (Postgres +
magic-link Auth) · a separate Python worker on Fly.io · Resend for email.
Scraping lives in the worker, never in Next.js API routes.

## Status

- [x] **Step 1 — Skeleton + auth.** Next.js app, Supabase client/server/proxy
      helpers, magic-link login, protected `(app)` route group, sign-out.
- [x] **Step 2 — Migrations.** `supabase/migrations/` holds the initial schema:
      the item/source/variant model (a watch groups many URLs, manual linking),
      RLS, the `my_watchlist` view. Verify with `./scripts/verify-migrations.sh`
      (needs local Postgres 15+; applies to a throwaway DB and smoke-tests the
      view math + RLS).
- [x] **Step 3 — Dashboard.** `/watchlist` reads `my_watchlist` in one query;
      rows expand to a 90-day sparkline and inline-editable alert rules; mute,
      archive with undo; failing / unsupported / first-check states.
      `PriceLadder`, `WatchRow`, `Sparkline` in `components/`.
- [x] **Step 4 — Add-product flow.** `/add`: paste a URL → confirm the
      worker-detected price → set an alert. Manual fallback teaches the worker
      a JSON path from the price the user sees; nothing is saved from a guess.
      `/add?watch=<id>` links another retailer to an existing watch.
- [x] **Step 5 — Worker skeleton.** `worker/`: polite fetcher, polling
      scheduler, `POST /extract` API, alert emails, and Fly.io deploy config.
      `normalize_url`, `extract` and `evaluate` are still owner stubs. See
      [`worker/README.md`](worker/README.md).

## Owner stubs (yours to write)

| Stub | Tests |
| ---- | ----- |
| `worker/extract/normalize.py::normalize_url` | `worker/tests/test_normalize.py` |
| `worker/extract/base.py::extract` | `worker/tests/test_extract.py` |
| `worker/alerts.py::evaluate` | `worker/tests/test_alerts.py` |

`cd worker && uv run pytest -q` — those three files fail with
`NotImplementedError` until implemented; everything else passes. Where the
contract was ambiguous the tests make a call, marked `# CONTRACT CHOICE:`.
Until the stubs exist, `/extract` reports `not_implemented` (the add flow
falls back to the manual price), the scheduler only checks sources with a
learned path, and no alerts are sent.

## Local setup

```bash
pnpm install
cp .env.local.example .env.local   # fill in real Supabase values
pnpm dev                           # http://localhost:3000
```

`.env.local` needs `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` (Supabase → Project Settings → API), plus
`WORKER_URL` and `WORKER_SHARED_SECRET` (server-only) for the add flow. The
service-role key / DB connection string is **not** used by this app — it is
worker-only. The worker's own setup is in [`worker/README.md`](worker/README.md);
the app ↔ worker contract is [`docs/worker-api.md`](docs/worker-api.md).

### Scripts

| Command           | What it does                                            |
| ----------------- | ------------------------------------------------------- |
| `pnpm dev`        | Dev server                                              |
| `pnpm build`      | Production build                                        |
| `pnpm typecheck`  | `tsc --noEmit`                                           |
| `pnpm lint`       | ESLint                                                  |
| `pnpm gen:types`  | Regenerate `lib/supabase/database.types.ts` from the DB |

`lib/supabase/database.types.ts` is a **placeholder** until you run
`SUPABASE_PROJECT_ID=<ref> pnpm gen:types` (needs the Supabase CLI). DB types
are generated, never hand-written.

## Auth flow

1. `/login` posts an email to `signInWithOtp` (magic link).
2. The email link returns to `/auth/confirm?code=…`, which exchanges the code
   for a session cookie and redirects to `/watchlist`.
3. `proxy.ts` refreshes the session on every request and gates the `(app)`
   group — unauthenticated → `/login`, authenticated-on-`/login` → `/watchlist`.

## Deploy to Vercel

1. `vercel login`, then `vercel link` in this directory.
2. Add env vars (Production + Preview): `NEXT_PUBLIC_SUPABASE_URL`,
   `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `WORKER_URL` (the Fly app's URL) and
   `WORKER_SHARED_SECRET` (same value as the worker's).
3. In Supabase → Auth → URL Configuration, add the Vercel URL to **Redirect
   URLs** (e.g. `https://<app>.vercel.app/auth/confirm`).
4. `vercel --prod`.

## Go-live checklist

1. **Database:** `supabase link --project-ref <ref>` then `supabase db push`
   to apply `supabase/migrations/`. Then `SUPABASE_PROJECT_ID=<ref> pnpm gen:types`
   (should match the committed `database.types.ts`).
2. **Resend:** verify a sending domain; create an API key.
3. **Worker (Fly):** follow [`worker/README.md`](worker/README.md) — `fly launch
   --no-deploy`, `fly secrets set DATABASE_URL=… WORKER_SHARED_SECRET=…
   RESEND_API_KEY=… ALERT_FROM_EMAIL=… APP_URL=…`, `fly deploy`,
   `fly scale count web=1 scheduler=1`.
4. **App (Vercel):** the steps above, with `WORKER_URL` pointing at the Fly app.
5. **Stubs:** implement the three owner stubs until `uv run pytest` is green.
