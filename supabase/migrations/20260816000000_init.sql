-- ============================================================
-- price tracker — initial schema (supabase / postgres)
--
-- MODEL: two layers.
--
--   GLOBAL (worker writes, every signed-in user reads, deduped):
--     product_sources  one row per canonical URL (url_hash UNIQUE)
--       └─ variants     one row per (source, "size|color")
--            └─ price_points   append-only, delta-logged + 24h heartbeat
--
--   PER-USER (RLS owner-only):
--     watches          a user's named grouping + alert rules
--       └─ watch_sources   the manual link: which URLs are "the same item"
--     notifications    sent log (exists to make debouncing correct)
--
-- Prices are integer cents everywhere. A "product" the user watches is the
-- WATCH (a grouping of sources), not any single URL — so tracking one item
-- across several retailers is just several rows in watch_sources.
-- ============================================================

create extension if not exists pgcrypto;

-- ------------------------------------------------------------
-- enums
-- ------------------------------------------------------------
create type extractor_kind as enum ('jsonld', 'nextdata', 'microdata', 'css', 'manual');
create type source_status  as enum ('active', 'failing', 'unsupported', 'paused');
create type notify_channel as enum ('email', 'ntfy', 'telegram', 'none');
create type alert_reason   as enum ('below_threshold', 'pct_drop', 'new_low', 'back_in_stock');

-- ------------------------------------------------------------
-- product_sources: one canonical URL. deduped by url_hash so a URL is
-- fetched once no matter how many users link it. the worker's queue.
-- ------------------------------------------------------------
create table product_sources (
  id                   uuid primary key default gen_random_uuid(),
  canonical_url        text not null,
  -- normalize before hashing (strip utm_*/gclid/etc, sort params, lowercase
  -- host). produced by worker/extract/normalize.py. this is what dedupes.
  url_hash             text not null unique,
  retailer             text not null,
  title                text,
  image_url            text,

  extractor            extractor_kind not null default 'jsonld',
  -- e.g. {"path": "props.pageProps.product.price.amount"} (nextdata)
  -- or   {"selector": ".price__current"} (css)
  extractor_config     jsonb not null default '{}'::jsonb,
  needs_browser        boolean not null default false,

  status               source_status not null default 'active',
  check_interval_mins  integer not null default 360,
  last_checked_at      timestamptz,
  next_check_at        timestamptz not null default now(),
  consecutive_failures integer not null default 0,
  last_error           text,

  created_by           uuid references auth.users(id) on delete set null,
  created_at           timestamptz not null default now()
);

-- the worker asks "what's due?" — keep the index tight to checkable rows.
create index sources_due_idx
  on product_sources (next_check_at)
  where status in ('active', 'failing');

-- ------------------------------------------------------------
-- variants: one per size/color on a source. price + stock differ per
-- variant (M in stock @ $50 while XL sold out), so history hangs here.
-- ------------------------------------------------------------
create table variants (
  id          uuid primary key default gen_random_uuid(),
  source_id   uuid not null references product_sources(id) on delete cascade,
  -- normalized "size|color"; '' (not null) for single-variant products so
  -- the unique constraint dedupes cleanly.
  variant_key text not null default '',
  size        text,
  color       text,
  sku         text,
  created_at  timestamptz not null default now(),
  unique (source_id, variant_key)
);

create index variants_source_idx on variants (source_id);

-- ------------------------------------------------------------
-- price_points: append-only, the big table. worker writes a row only when
-- price or stock CHANGED, or >24h since the last row (the heartbeat that
-- keeps the row-based medians/percentiles ~time-weighted).
-- ------------------------------------------------------------
create table price_points (
  id          bigserial primary key,
  variant_id  uuid not null references variants(id) on delete cascade,
  observed_at timestamptz not null default now(),
  price_cents integer not null check (price_cents >= 0),
  currency    char(3) not null default 'USD',
  in_stock    boolean not null default true
);

-- covers "latest price" and the trailing 90d window.
create index price_points_series_idx on price_points (variant_id, observed_at desc);
-- the worker enforces delta-logging; this catches exact-timestamp dupes.
create unique index price_points_no_dupe on price_points (variant_id, observed_at);

-- ------------------------------------------------------------
-- watches: the per-user layer. this is the "item" the user tracks.
-- ------------------------------------------------------------
create table watches (
  id                   uuid primary key default gen_random_uuid(),
  user_id              uuid not null references auth.users(id) on delete cascade,
  nickname             text,
  -- null = alert on any variant; else only these "size|color" keys.
  watched_variant_keys text[],

  -- alert rules. null threshold = that rule off.
  alert_below_cents    integer      check (alert_below_cents is null or alert_below_cents >= 0),
  alert_pct_drop       numeric(5,2) check (alert_pct_drop  is null or alert_pct_drop > 0), -- vs 30d median
  alert_on_new_low     boolean not null default true,   -- vs 90d minimum
  alert_on_restock     boolean not null default true,   -- back_in_stock

  channel              notify_channel not null default 'email',
  muted_until          timestamptz,
  min_alert_gap_hrs    integer not null default 24,

  archived_at          timestamptz,
  created_at           timestamptz not null default now()
);

create index watches_user_idx on watches (user_id) where archived_at is null;

-- ------------------------------------------------------------
-- watch_sources: the manual link. a watch groups 1..N URLs the user
-- asserts are the same item. never auto-matched.
-- ------------------------------------------------------------
create table watch_sources (
  watch_id  uuid not null references watches(id) on delete cascade,
  source_id uuid not null references product_sources(id) on delete cascade,
  added_at  timestamptz not null default now(),
  primary key (watch_id, source_id)
);

create index watch_sources_source_idx on watch_sources (source_id);

-- ------------------------------------------------------------
-- notifications: sent log. makes debouncing correct.
-- ------------------------------------------------------------
create table notifications (
  id          bigserial primary key,
  watch_id    uuid not null references watches(id) on delete cascade,
  source_id   uuid references product_sources(id) on delete set null,
  variant_id  uuid references variants(id) on delete set null,
  sent_at     timestamptz not null default now(),
  reason      alert_reason not null,
  price_cents integer not null,
  delivered   boolean not null default false,
  error       text
);

create index notifications_recent_idx on notifications (watch_id, sent_at desc);

-- ============================================================
-- row level security
--
-- global tables (sources/variants/price_points): any signed-in user may
-- READ — a public retail price isn't private, and making it private forces
-- a join on every history query. WRITES to variants/price_points are
-- worker-only (service role bypasses RLS); the app never writes a price.
-- watches/watch_sources/notifications: strictly owner-only.
-- ============================================================
alter table product_sources enable row level security;
alter table variants        enable row level security;
alter table price_points    enable row level security;
alter table watches         enable row level security;
alter table watch_sources   enable row level security;
alter table notifications   enable row level security;

-- product_sources: read all; a user may create a source (created_by = them).
-- no update/delete policy — only the service-role worker mutates check state.
create policy sources_read on product_sources
  for select to authenticated using (true);
create policy sources_insert on product_sources
  for insert to authenticated with check (created_by = auth.uid());

-- variants + price_points: read-only to users; worker owns writes.
create policy variants_read on variants
  for select to authenticated using (true);
create policy price_points_read on price_points
  for select to authenticated using (true);

-- watches: full owner-only access.
create policy watches_all on watches
  for all to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- watch_sources: manageable only through a watch you own.
create policy watch_sources_all on watch_sources
  for all to authenticated
  using (exists (
    select 1 from watches w
    where w.id = watch_sources.watch_id and w.user_id = auth.uid()
  ))
  with check (exists (
    select 1 from watches w
    where w.id = watch_sources.watch_id and w.user_id = auth.uid()
  ));

-- notifications: read your own; worker (service role) inserts.
create policy notifications_read on notifications
  for select to authenticated
  using (exists (
    select 1 from watches w
    where w.id = notifications.watch_id and w.user_id = auth.uid()
  ));

-- ============================================================
-- abuse / cost guard: cap LINKED SOURCES per user (fetch cost), not
-- watches. a watch can now pull many URLs, and each URL costs fetches
-- forever, so the source count is the thing to bound.
-- ============================================================
create or replace function enforce_source_cap() returns trigger
language plpgsql as $$
declare
  owner uuid;
  n integer;
begin
  select user_id into owner from watches where id = new.watch_id;
  select count(*) into n
    from watch_sources ws
    join watches w on w.id = ws.watch_id
   where w.user_id = owner and w.archived_at is null;
  if n >= 100 then
    raise exception 'linked-source limit reached'
      using hint = 'Archive a watch or remove a linked URL.';
  end if;
  return new;
end $$;

create trigger watch_sources_cap
  before insert on watch_sources
  for each row execute function enforce_source_cap();

-- ============================================================
-- my_watchlist: the one view the dashboard reads. one row per active
-- watch. all percentile/median math stays here in SQL.
--
-- verdict/ladder are computed over the currently-cheapest linked listing's
-- own 90-day history: current price = cheapest in-stock variant across the
-- watch's sources; that variant's distribution drives low/high/median/rank.
-- display info comes from a stable "display source" so a just-added,
-- not-yet-checked watch still renders.
-- ============================================================
create view my_watchlist
with (security_invoker = true) as
with candidate as (
  -- every watched variant with its latest observation
  select
    w.id          as watch_id,
    v.id          as variant_id,
    v.source_id,
    v.variant_key,
    latest.price_cents,
    latest.in_stock,
    latest.observed_at
  from watches w
  join watch_sources ws on ws.watch_id = w.id
  join variants v       on v.source_id = ws.source_id
  left join lateral (
    select pp.price_cents, pp.in_stock, pp.observed_at
      from price_points pp
     where pp.variant_id = v.id
     order by pp.observed_at desc
     limit 1
  ) latest on true
  where w.archived_at is null
    and (w.watched_variant_keys is null
         or v.variant_key = any (w.watched_variant_keys))
),
best as (
  -- cheapest currently-available variant per watch (prefer in stock)
  select distinct on (watch_id)
    watch_id, variant_id, source_id, variant_key,
    price_cents, in_stock, observed_at
  from candidate
  where price_cents is not null
  order by watch_id, in_stock desc, price_cents asc
)
select
  w.id                          as watch_id,
  w.nickname,
  w.watched_variant_keys,
  w.alert_below_cents,
  w.alert_pct_drop,
  w.alert_on_new_low,
  w.alert_on_restock,
  w.channel,
  w.muted_until,
  coalesce(w.nickname, disp.title) as display_title,
  disp.source_id,
  disp.retailer,
  disp.canonical_url,
  disp.image_url,
  disp.status,
  disp.last_checked_at,
  disp.consecutive_failures,
  (select count(*) from watch_sources ws2 where ws2.watch_id = w.id) as source_count,
  exists (
    select 1 from watch_sources ws3
    join product_sources s3 on s3.id = ws3.source_id
    where ws3.watch_id = w.id and s3.status = 'failing'
  )                             as has_failing_source,
  best.variant_id,
  best.variant_key              as current_variant_key,
  best.price_cents              as current_cents,
  best.in_stock,
  best.observed_at              as current_observed_at,
  stats.low_90_cents,
  stats.high_90_cents,
  stats.median_30_cents,
  stats.pct_rank_90
from watches w
-- stable display source: prefer one with a title, then earliest linked.
left join lateral (
  select s.id as source_id, s.title, s.retailer, s.canonical_url,
         s.image_url, s.status, s.last_checked_at, s.consecutive_failures
    from watch_sources ws
    join product_sources s on s.id = ws.source_id
   where ws.watch_id = w.id
   order by (s.title is null), ws.added_at asc
   limit 1
) disp on true
left join best on best.watch_id = w.id
left join lateral (
  select
    min(price_cents) as low_90_cents,
    max(price_cents) as high_90_cents,
    percentile_cont(0.5) within group (order by price_cents)
      filter (where observed_at > now() - interval '30 days') as median_30_cents,
    -- where today's price sits in its own 90d distribution (0 = cheapest ever)
    100.0 * avg(case when price_cents < best.price_cents then 1 else 0 end)
      as pct_rank_90
  from price_points
  where variant_id = best.variant_id
    and observed_at > now() - interval '90 days'
) stats on true
where w.archived_at is null;
