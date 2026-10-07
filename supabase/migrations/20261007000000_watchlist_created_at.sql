-- Append w.created_at to my_watchlist so the dashboard can sort by it in SQL.
-- `create or replace view` only allows appending columns, so it goes last.
-- The body is otherwise identical to the init migration.

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
create or replace view my_watchlist
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
  stats.pct_rank_90,
  w.created_at
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
