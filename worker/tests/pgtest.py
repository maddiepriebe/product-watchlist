"""Throwaway-database helpers for DB integration tests.

Set TEST_DATABASE_URL to a Postgres 15+ server you can create databases on
(e.g. postgresql://postgres@127.0.0.1:55450/postgres). Each test gets a fresh
database with the Supabase shim and every migration applied; without the
var, DB tests skip.

Not conftest.py on purpose: that name is reserved for the stub tests. Test
modules import the fixtures from here.
"""

import os
import uuid
from pathlib import Path
from typing import AsyncIterator, Iterator

import psycopg
import pytest
import pytest_asyncio
from psycopg import conninfo

from db import Database

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")

requires_db = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="set TEST_DATABASE_URL to run DB integration tests"
)

# Mirrors the shim in scripts/verify-migrations.sh: the bits of Supabase's
# auth schema and roles the migrations reference.
SHIM = """
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
"""


@pytest.fixture
def db_url() -> Iterator[str]:
    name = f"wl_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
        admin.execute(f'create database "{name}"')
    url = conninfo.make_conninfo(TEST_DATABASE_URL, dbname=name)
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SHIM)
            for f in sorted(MIGRATIONS.glob("*.sql")):
                conn.execute(f.read_text())
        yield url
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
            admin.execute(f'drop database if exists "{name}" with (force)')


@pytest_asyncio.fixture
async def database(db_url: str) -> AsyncIterator[Database]:
    db = Database(db_url, size=2)
    try:
        yield db
    finally:
        await db.close()


def sql(url: str, query: str, params: tuple = ()) -> list[tuple]:
    """Synchronous helper for seeding and asserting."""
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else []


USER_ID = "11111111-1111-1111-1111-111111111111"


def seed_source(url: str, *, retailer: str = "farmrio.com", status: str = "active",
                due: bool = True, extractor_config: str = "{}", failures: int = 0) -> str:
    sql(url, "insert into auth.users (id, email) values (%s, 'a@test.dev') on conflict do nothing", (USER_ID,))
    sid = str(uuid.uuid4())
    sql(
        url,
        """
        insert into product_sources (id, canonical_url, url_hash, retailer, status,
                                     next_check_at, extractor_config, consecutive_failures, created_by)
        values (%s, %s, %s, %s, %s::source_status,
                now() + case when %s then interval '-1 minute' else interval '1 hour' end,
                %s::jsonb, %s, %s)
        """,
        (sid, f"https://{retailer}/p/{sid}", f"hash-{sid}", retailer, status, due,
         extractor_config, failures, USER_ID),
    )
    return sid
