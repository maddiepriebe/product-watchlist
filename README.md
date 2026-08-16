# Product Watchlist

Multi-user price tracking. Users watch products; when a price drops or a
sold-out size returns, they get an email.

**Stack:** Next.js (App Router, TS, Tailwind) on Vercel · Supabase (Postgres +
magic-link Auth) · a separate Python worker on Fly.io · Resend for email.
Scraping lives in the worker, never in Next.js API routes.

## Status

- [x] **Step 1 — Skeleton + auth.** Next.js app, Supabase client/server/proxy
      helpers, magic-link login, protected `(app)` route group, sign-out.
- [ ] Step 2 — Migrations
- [ ] Step 3 — Dashboard
- [ ] Step 4 — Add-product flow
- [ ] Step 5 — Worker skeleton

## Local setup

```bash
pnpm install
cp .env.local.example .env.local   # fill in real Supabase values
pnpm dev                           # http://localhost:3000
```

`.env.local` needs `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` (Supabase → Project Settings → API). The
service-role key is **not** used by this app — it is worker-only.

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
2. Add env vars: `vercel env add NEXT_PUBLIC_SUPABASE_URL` and
   `vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY` (Production + Preview).
3. In Supabase → Auth → URL Configuration, add the Vercel URL to **Redirect
   URLs** (e.g. `https://<app>.vercel.app/auth/confirm`).
4. `vercel --prod`.
