-- ============================================================
-- my_watch_sources: one row per (active watch, linked source), with that
-- source's own current best price. The dashboard's expanded row lists these
-- so the user can see every retailer a watch is linked to.
--
-- "Current best" mirrors the candidate/best CTEs of my_watchlist, but
-- partitioned by source instead of by watch: the cheapest latest point among
-- the source's variants that match the watch's variant filter, preferring in
-- stock. is_cheapest flags the one source my_watchlist would also pick, so
-- the app never has to compare prices itself.
--
-- security_invoker: RLS on watches / watch_sources applies to the caller, so
-- a user only ever sees their own links.
-- ============================================================
create view my_watch_sources
with (security_invoker = true) as
with candidate as (
  -- every watched variant of every linked source, with its latest observation
  select
    ws.watch_id,
    ws.source_id,
    v.variant_key,
    latest.price_cents,
    latest.in_stock
  from watches w
  join watch_sources ws on ws.watch_id = w.id
  join variants v       on v.source_id = ws.source_id
  left join lateral (
    select pp.price_cents, pp.in_stock
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
  -- cheapest currently-available variant per (watch, source), prefer in stock
  select distinct on (watch_id, source_id)
    watch_id, source_id, variant_key, price_cents, in_stock
  from candidate
  where price_cents is not null
  order by watch_id, source_id, in_stock desc, price_cents asc
),
ranked as (
  -- same ordering my_watchlist uses to pick a watch's current price
  select
    watch_id, source_id,
    row_number() over (
      partition by watch_id order by in_stock desc, price_cents asc, source_id
    ) = 1 as is_cheapest
  from best
)
select
  ws.watch_id,
  ws.source_id,
  s.retailer,
  s.title,
  s.canonical_url,
  s.status,
  s.last_checked_at,
  s.last_error,
  ws.added_at,
  best.price_cents  as current_cents,
  best.in_stock,
  best.variant_key  as current_variant_key,
  coalesce(ranked.is_cheapest, false) as is_cheapest
from watches w
join watch_sources ws   on ws.watch_id = w.id
join product_sources s  on s.id = ws.source_id
left join best   on best.watch_id = ws.watch_id and best.source_id = ws.source_id
left join ranked on ranked.watch_id = ws.watch_id and ranked.source_id = ws.source_id
where w.archived_at is null;
