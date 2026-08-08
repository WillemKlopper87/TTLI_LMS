from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from src.core.db import get_sessionmaker

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness — checks the database")
async def ready() -> dict[str, Any]:
    factory = get_sessionmaker()
    async with factory() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


__all__ = ["router"]
