"""Environment configuration.

Each process asks only for the vars it needs (the web API never touches the
DB; the scheduler never checks bearer tokens) and fails at startup, listing
every missing var at once, rather than on the first request that needs one.
"""

import os
from dataclasses import dataclass
from typing import Iterable, Mapping

API_REQUIRED = ("WORKER_SHARED_SECRET",)
SCHEDULER_REQUIRED = ("DATABASE_URL", "RESEND_API_KEY", "ALERT_FROM_EMAIL", "APP_URL")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str = ""
    worker_shared_secret: str = ""
    resend_api_key: str = ""
    alert_from_email: str = ""
    app_url: str = ""
    port: int = 8080

    # Scheduler tuning. Defaults suit one small Fly machine.
    batch_size: int = 20           # sources claimed per poll
    concurrency: int = 8           # sources processed at once (per-domain is still 1)
    lease_mins: int = 15           # how long a claimed source is hidden from other workers
    idle_sleep_s: float = 30.0     # base sleep when nothing is due (jittered)
    db_pool_size: int = 4

    # Fetch politeness.
    domain_delay_s: float = 2.0    # minimum gap between requests to one domain
    domain_jitter_s: float = 1.5   # plus up to this much random extra
    fetch_timeout_s: float = 20.0


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from e


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from e


def load_settings(
    required: Iterable[str] = (), env: Mapping[str, str] | None = None
) -> Settings:
    env = os.environ if env is None else env
    missing = [name for name in required if not env.get(name, "").strip()]
    if missing:
        raise ConfigError(
            "Missing required environment variables: " + ", ".join(missing)
            + ". See worker/.env.example."
        )
    d = Settings()
    return Settings(
        database_url=env.get("DATABASE_URL", "").strip(),
        worker_shared_secret=env.get("WORKER_SHARED_SECRET", "").strip(),
        resend_api_key=env.get("RESEND_API_KEY", "").strip(),
        alert_from_email=env.get("ALERT_FROM_EMAIL", "").strip(),
        # Links are built as f"{app_url}/watchlist"; a trailing slash would double up.
        app_url=env.get("APP_URL", "").strip().rstrip("/"),
        port=_int(env, "PORT", d.port),
        batch_size=_int(env, "WORKER_BATCH_SIZE", d.batch_size),
        concurrency=_int(env, "WORKER_CONCURRENCY", d.concurrency),
        lease_mins=_int(env, "WORKER_LEASE_MINS", d.lease_mins),
        idle_sleep_s=_float(env, "WORKER_IDLE_SLEEP_S", d.idle_sleep_s),
        db_pool_size=_int(env, "WORKER_DB_POOL_SIZE", d.db_pool_size),
        domain_delay_s=_float(env, "FETCH_DOMAIN_DELAY_S", d.domain_delay_s),
        domain_jitter_s=_float(env, "FETCH_DOMAIN_JITTER_S", d.domain_jitter_s),
        fetch_timeout_s=_float(env, "FETCH_TIMEOUT_S", d.fetch_timeout_s),
    )
