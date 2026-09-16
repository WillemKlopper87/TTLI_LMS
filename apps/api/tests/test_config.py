from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError
from src.core.config import Settings, check_production_safety

GOOD_KEY = base64.b64encode(b"A" * 32).decode()
OTHER_KEY = base64.b64encode(b"B" * 32).decode()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "production",
        "debug": False,
        "secret_key": "x" * 48,
        "database_url": "postgresql+asyncpg://u:p@db.internal:5432/ttli",
        "field_encryption_key": GOOD_KEY,
        "blind_index_key": OTHER_KEY,
        "break_glass_admin_enabled": False,
        "storage_backend": "s3",
        "s3_access_key": "AKIAREAL",
        "sentry_dsn": "https://key@sentry.io/1",
        "app_db_password": "K9mP2xQ7vN4wZ8bR",
        "redis_url": "redis://u:p@redis.internal:6379/0",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_database_url_must_use_asyncpg() -> None:
    with pytest.raises(ValidationError, match="asyncpg"):
        Settings(database_url="postgresql://u:p@localhost/ttli")  # type: ignore[call-arg]


def test_non_production_is_never_blocked() -> None:
    s = _settings(environment="local", debug=True, break_glass_admin_enabled=True, sentry_dsn="")
    assert check_production_safety(s) == []


def test_a_correct_production_config_passes() -> None:
    assert check_production_safety(_settings()) == []


def test_debug_in_production_is_refused() -> None:
    assert "DEBUG is enabled" in check_production_safety(_settings(debug=True))


def test_break_glass_admin_in_production_is_refused() -> None:
    problems = check_production_safety(_settings(break_glass_admin_enabled=True))
    assert any("BREAK_GLASS" in p for p in problems)


def test_shared_encryption_and_index_key_is_refused() -> None:
    problems = check_production_safety(_settings(blind_index_key=GOOD_KEY))
    assert any("same value" in p for p in problems)


def test_localhost_database_in_production_is_refused() -> None:
    problems = check_production_safety(
        _settings(database_url="postgresql+asyncpg://u:p@localhost:5432/ttli")
    )
    assert any("localhost" in p for p in problems)


def test_development_storage_credentials_are_refused() -> None:
    problems = check_production_safety(_settings(s3_access_key="ttli_dev"))
    assert any("development credential" in p for p in problems)


def test_every_problem_is_reported_at_once() -> None:
    """A list, not a boolean — one redeploy per discovered problem is not a workflow."""
    problems = check_production_safety(
        _settings(
            debug=True,
            break_glass_admin_enabled=True,
            secret_key="short",
            storage_backend="local",
            sentry_dsn="",
        )
    )
    assert len(problems) >= 5


def test_sync_url_is_derived_when_not_set() -> None:
    s = _settings(database_url_sync="")
    assert s.sync_database_url.startswith("postgresql+psycopg2://")


def test_missing_app_db_password_in_production_is_refused() -> None:
    problems = check_production_safety(_settings(app_db_password=""))
    assert any("APP_DB_PASSWORD is not set" in p for p in problems)


def test_development_app_db_password_is_refused() -> None:
    problems = check_production_safety(_settings(app_db_password="app_user_local_dev"))
    assert any("development credential" in p for p in problems)


def test_localhost_redis_in_production_is_refused() -> None:
    problems = check_production_safety(_settings(redis_url="redis://localhost:6399/0"))
    assert any("REDIS_URL" in p for p in problems)


def test_the_transcode_job_carries_an_explicit_timeout() -> None:
    """arq's own default is 300 seconds, which silently cancels any
    transcode longer than five minutes — i.e. most real lecture video
    (fable5.1 review H-5). The point is that the value is *ours*, chosen
    and visible, rather than a framework default nobody looked at.
    """
    from src.workers.main import WorkerSettings

    transcode = next(
        f for f in WorkerSettings.functions if getattr(f, "name", "") == "transcode_video_job"
    )
    assert transcode.timeout_s == _settings().transcode_job_timeout_seconds
    assert transcode.timeout_s > 300, "still inside arq's default, which is the bug"


def test_worker_health_check_interval_is_not_arqs_hour_long_default() -> None:
    """BACKLOG T10 / the compose worker healthcheck depends on this: arq
    writes its Redis health-check sentinel with a TTL of
    health_check_interval + 1 seconds and only refreshes it that often.
    arq's own default (3600s) would leave a dead worker's sentinel reading
    "healthy" for up to an hour — exactly the false-positive `wait_running`
    used to hide. The value is *ours*, chosen to fit inside
    scripts/rolling-update.sh's HEALTH_TIMEOUT (60s default), not a
    framework default nobody looked at (same shape as the transcode-timeout
    test above).
    """
    from src.workers.main import WorkerSettings

    assert WorkerSettings.health_check_interval == 30
    assert WorkerSettings.health_check_interval < 60, (
        "must clear inside rolling-update.sh's HEALTH_TIMEOUT default, or a "
        "dead worker could still read healthy for the whole deploy window"
    )
