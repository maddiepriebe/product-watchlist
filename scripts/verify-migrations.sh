#!/usr/bin/env bash
#
# Verify every migration in supabase/migrations/ applies cleanly, in order, to
# an empty database — with a small shim for the Supabase-provided auth schema,
# auth.uid(), and the anon/authenticated/service_role roles. Also smoke-tests
# the my_watchlist view math and RLS.
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

echo "OK — all migrations apply and checks pass."
