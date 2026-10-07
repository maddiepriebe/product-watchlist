import pytest

from config import SCHEDULER_REQUIRED, ConfigError, load_settings


def test_missing_vars_are_all_listed() -> None:
    with pytest.raises(ConfigError) as e:
        load_settings(SCHEDULER_REQUIRED, env={"DATABASE_URL": "postgres://x"})
    msg = str(e.value)
    for name in ("RESEND_API_KEY", "ALERT_FROM_EMAIL", "APP_URL"):
        assert name in msg
    assert "DATABASE_URL" not in msg


def test_blank_counts_as_missing() -> None:
    with pytest.raises(ConfigError):
        load_settings(["WORKER_SHARED_SECRET"], env={"WORKER_SHARED_SECRET": "  "})


def test_parses_values_and_trims_app_url() -> None:
    s = load_settings(
        [],
        env={"APP_URL": "https://app.test/", "PORT": "9000", "WORKER_BATCH_SIZE": "5"},
    )
    assert s.app_url == "https://app.test"
    assert s.port == 9000
    assert s.batch_size == 5


def test_bad_number_fails_loudly() -> None:
    with pytest.raises(ConfigError):
        load_settings([], env={"PORT": "eighty"})
