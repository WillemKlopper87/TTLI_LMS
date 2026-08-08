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
