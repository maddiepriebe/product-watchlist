#!/usr/bin/env bash
#
# Verify every migration in supabase/migrations/ applies cleanly, in order, to
# an empty database — with a small shim for the Supabase-provided auth schema,
# auth.uid(), and the anon/authenticated/service_role roles. Also smoke-tests
# the my_watchlist / my_watch_sources view math and RLS.
#
# Requires Postgres 15+ locally (Supabase runs 15+; `security_invoker` views
# and other features need it). Uses postgresql@15 from Homebrew if present.
#
# Usage: ./scripts/verify-migrations.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
MIGRATIONS="$REPO/supabase/migrations"
WORK="$(mktemp -d)"
export PGDATA="$WORK/data"
PORT="${PGPORT:-55433}"

# Prefer a 15+ toolchain.
for v in 17 16 15; do
  if [ -x "/opt/homebrew/opt/postgresql@$v/bin/initdb" ]; then
    export PATH="/opt/homebrew/opt/postgresql@$v/bin:$PATH"; break
  fi
done

cleanup() { pg_ctl -D "$PGDATA" -w -m immediate stop >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT

echo "postgres: $(initdb --version)"
mkdir -p "$PGDATA"
initdb -D "$PGDATA" -U postgres --auth=trust >/dev/null 2>&1
pg_ctl -D "$PGDATA" -o "-c listen_addresses='127.0.0.1' -p $PORT" -w start >/dev/null 2>&1
PSQL="psql -h 127.0.0.1 -p $PORT -U postgres -v ON_ERROR_STOP=1 -q"

$PSQL -d postgres -c "create database watchlist_test;"
DB="$PSQL -d watchlist_test"

echo "### shim: Supabase auth schema + roles ###"
$DB <<'SQL'
create extension if not exists pgcrypto;
create schema if not exists auth;
create table auth.users (id uuid primary key default gen_random_uuid(), email text);
create function auth.uid() returns uuid language sql stable as
  $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
do $$ begin
  if not exists (select from pg_roles where rolname='anon') then create role anon; end if;
  if not exists (select from pg_roles where rolname='authenticated') then create role authenticated; end if;
  if not exists (select from pg_roles where rolname='service_role') then create role service_role; end if;
end $$;
SQL

echo "### applying migrations in order ###"
for f in $(ls "$MIGRATIONS"/*.sql | sort); do
  echo "  -> $(basename "$f")"
  $DB -f "$f"
done
$DB <<'SQL'
grant usage on schema public to authenticated;
grant select, insert, update, delete on all tables in schema public to authenticated;
grant select on my_watchlist to authenticated;
grant select on my_watch_sources to authenticated;
SQL

echo "### seeding sample data ###"
$DB <<'SQL'
insert into auth.users (id, email) values
  ('11111111-1111-1111-1111-111111111111', 'a@test.dev'),
  ('22222222-2222-2222-2222-222222222222', 'b@test.dev');
insert into product_sources (id, canonical_url, url_hash, retailer, title, created_by)
values ('aaaaaaaa-0000-0000-0000-000000000001',
        'https://shop.test/dress', 'hash-dress', 'Test Shop', 'Rustic Dress',
        '11111111-1111-1111-1111-111111111111');
insert into variants (id, source_id, variant_key) values
  ('bbbbbbbb-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-000000000001', 'M|black'),
  ('bbbbbbbb-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-000000000001', 'XL|black');
insert into price_points (variant_id, observed_at, price_cents, in_stock) values
  ('bbbbbbbb-0000-0000-0000-000000000001', now() - interval '89 days', 10000, true),
  ('bbbbbbbb-0000-0000-0000-000000000001', now() - interval '60 days', 10000, true),
  ('bbbbbbbb-0000-0000-0000-000000000001', now() - interval '20 days',  8000, true),
  ('bbbbbbbb-0000-0000-0000-000000000001', now() - interval '5 days',   6000, true),
  ('bbbbbbbb-0000-0000-0000-000000000001', now(),                       5000, true),
  ('bbbbbbbb-0000-0000-0000-000000000002', now(), 4000, false);
insert into watches (id, user_id) values
  ('cccccccc-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111');
insert into watch_sources (watch_id, source_id) values
  ('cccccccc-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-000000000001');
SQL

echo "### my_watchlist (expect current=5000 in-stock, low=5000 high=10000 median30=6000 rank=0) ###"
$DB -P pager=off -c "select display_title, current_variant_key, current_cents, in_stock,
      low_90_cents, high_90_cents, median_30_cents, round(pct_rank_90::numeric,1) as rank,
      source_count, has_failing_source from my_watchlist;"

echo "### RLS: owner=1 stranger=0 ###"
echo -n "  owner:    "; $DB -tA -c "set local role authenticated; set local request.jwt.claim.sub='11111111-1111-1111-1111-111111111111'; select count(*) from my_watchlist;"
echo -n "  stranger: "; $DB -tA -c "set local role authenticated; set local request.jwt.claim.sub='22222222-2222-2222-2222-222222222222'; select count(*) from my_watchlist;"

echo -n "### RLS write guard (cross-user link must fail): "
if $DB -c "set local role authenticated; set local request.jwt.claim.sub='22222222-2222-2222-2222-222222222222';
  insert into watch_sources (watch_id, source_id) values ('cccccccc-0000-0000-0000-000000000001','aaaaaaaa-0000-0000-0000-000000000001');" >/dev/null 2>&1
then echo "ALLOWED (BUG!)"; exit 1; else echo "blocked (correct) ###"; fi

echo "### my_watchlist.created_at is the last column ###"
echo -n "  last column: "; $DB -tA -c "select column_name from information_schema.columns
  where table_name = 'my_watchlist' order by ordinal_position desc limit 1;"

echo "### seeding a multi-source watch + a variant-filtered watch ###"
$DB <<'SQL'
insert into product_sources (id, canonical_url, url_hash, retailer, title, status, last_error, created_by) values
  ('aaaaaaaa-0000-0000-0000-000000000002', 'https://other.test/dress', 'hash-dress-2', 'Other Shop', 'Rustic Dress', 'active', null,
   '11111111-1111-1111-1111-111111111111'),
  ('aaaaaaaa-0000-0000-0000-000000000003', 'https://broken.test/dress', 'hash-dress-3', 'Broken Shop', null, 'failing', 'no price found',
   '11111111-1111-1111-1111-111111111111');
insert into variants (id, source_id, variant_key) values
  ('bbbbbbbb-0000-0000-0000-000000000003', 'aaaaaaaa-0000-0000-0000-000000000002', 'M|black'),
  ('bbbbbbbb-0000-0000-0000-000000000004', 'aaaaaaaa-0000-0000-0000-000000000002', 'XL|black');
insert into price_points (variant_id, observed_at, price_cents, in_stock) values
  ('bbbbbbbb-0000-0000-0000-000000000003', now() - interval '2 days', 9000, true),
  ('bbbbbbbb-0000-0000-0000-000000000003', now(),                     4500, true),
  ('bbbbbbbb-0000-0000-0000-000000000004', now(),                     3000, false);
insert into watches (id, user_id, watched_variant_keys) values
  ('cccccccc-0000-0000-0000-000000000002', '11111111-1111-1111-1111-111111111111', null),
  ('cccccccc-0000-0000-0000-000000000003', '11111111-1111-1111-1111-111111111111', array['XL|black']);
insert into watch_sources (watch_id, source_id) values
  ('cccccccc-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-000000000001'),
  ('cccccccc-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-000000000002'),
  ('cccccccc-0000-0000-0000-000000000002', 'aaaaaaaa-0000-0000-0000-000000000003'),
  ('cccccccc-0000-0000-0000-000000000003', 'aaaaaaaa-0000-0000-0000-000000000001');
SQL

echo "### my_watch_sources as owner ###"
echo "  expect: watch ...02: Test Shop 5000 in-stock; Other Shop 4500 in-stock CHEAPEST (in-stock beats 3000 sold out);"
echo "          Broken Shop failing, no price. watch ...03 (XL filter): Test Shop 4000 out of stock, cheapest."
echo "          watch ...01: Test Shop 5000 cheapest."
OWNER_OUT="$($DB -tA -F '|' -c "set local role authenticated; set local request.jwt.claim.sub='11111111-1111-1111-1111-111111111111';
select right(watch_id::text, 2), retailer, status, coalesce(current_cents::text,'-'), coalesce(in_stock::text,'-'),
       coalesce(current_variant_key,'-'), is_cheapest
  from my_watch_sources order by watch_id, retailer;" | grep -v '^SET$')"
echo "$OWNER_OUT" | sed 's/^/  /'
EXPECTED="01|Test Shop|active|5000|true|M|black|t
02|Broken Shop|failing|-|-|-|f
02|Other Shop|active|4500|true|M|black|t
02|Test Shop|active|5000|true|M|black|f
03|Test Shop|active|4000|false|XL|black|t"
if [ "$OWNER_OUT" = "$EXPECTED" ]; then echo "  per-source prices correct"; else echo "  per-source prices WRONG (BUG!)"; echo "$EXPECTED" | sed 's/^/  expected: /'; exit 1; fi

echo -n "### my_watch_sources RLS: owner=5 stranger=0: "
N_OWNER="$($DB -tA -c "set local role authenticated; set local request.jwt.claim.sub='11111111-1111-1111-1111-111111111111'; select count(*) from my_watch_sources;" | grep -v '^SET$')"
N_STRANGER="$($DB -tA -c "set local role authenticated; set local request.jwt.claim.sub='22222222-2222-2222-2222-222222222222'; select count(*) from my_watch_sources;" | grep -v '^SET$')"
echo "owner=$N_OWNER stranger=$N_STRANGER"
if [ "$N_OWNER" != "5" ] || [ "$N_STRANGER" != "0" ]; then echo "RLS WRONG (BUG!)"; exit 1; fi

echo "OK — all migrations apply and checks pass."
