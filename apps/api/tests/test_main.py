"""App-construction guardrails that are settings-driven and don't belong
inside any one router's test file. The docs/openapi tests below build a
FastAPI app with no database or Redis needed — `create_app()` only
registers routers; it opens nothing until `lifespan` runs. The lifespan
test does run `lifespan()` itself, so it is marked `integration` like
any other test that touches a real engine.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from src.core.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://u:p@db.internal:5432/ttli",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_docs_ui_and_schema_are_both_disabled_in_production(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """L1: `docs_url` was already gated on `is_production`, but
    `openapi_url` was not — the full route schema (every admin/finance/
    privacy endpoint shape) was still served at `/openapi.json` in
    production regardless. Confirmed live during the 2026-09-19 pentest:
    `/docs` -> 404, `/openapi.json` -> 200."""
    import src.main as main_module

    monkeypatch.setattr(main_module, "get_settings", lambda: _settings())
    app = main_module.create_app()

    assert app.docs_url is None
    assert app.openapi_url is None


def test_docs_ui_and_schema_are_both_served_outside_production(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import src.main as main_module

    monkeypatch.setattr(main_module, "get_settings", lambda: _settings(environment="local"))
    app = main_module.create_app()

    assert app.docs_url == "/docs"
    assert app.openapi_url == "/openapi.json"


@pytest.mark.integration
async def test_lifespan_refuses_to_start_when_the_db_role_can_bypass_rls(
    monkeypatch, settings, database_url
) -> None:  # type: ignore[no-untyped-def]
    """L2: `lifespan()` must actually call the guard added in
    core/db.py — not just have it exist and pass its own unit test.
    Faking the check (rather than pointing DATABASE_URL at the real
    superuser) is enough to prove the wiring: the *behaviour* of the
    check itself is covered by tests/test_db.py against a real
    connection."""
    import src.main as main_module

    async def _fake_assert(engine: object) -> None:
        raise RuntimeError(
            "Refusing to start: the database role this app connects as "
            "(rolsuper=True, rolbypassrls=True) can bypass row-level security."
        )

    monkeypatch.setattr(main_module, "assert_app_role_cannot_bypass_rls", _fake_assert)

    with pytest.raises(RuntimeError, match="bypass row-level security"):
        async with main_module.lifespan(FastAPI()):
            pass
