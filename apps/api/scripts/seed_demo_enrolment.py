"""Enrol the local demo account in a demo programme.

The learner dashboard, the player and the credential panel only have
anything to show once someone is actually enrolled. Buying a course
end-to-end (order → EFT → proof → finance approval) is the real path and
is covered by the test suite; this script exists so the *demo* database
has a learner without needing a human to walk that flow every time the
database is reset.

It grants a course entitlement and an enrolment directly — the same two
rows `services/orders.py` writes on approval — and nothing else: no
order, no payment and no invoice is fabricated, so the finance figures
stay honest.

    apps/api/.venv/Scripts/python.exe scripts/seed_demo_enrolment.py [slug]

Idempotent, and local/dev only.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from src.core.config import get_settings
from src.core.db import get_sessionmaker, init_engine, set_tenant
from src.core.ids import uuid7
from src.models.commerce import Entitlement
from src.models.course import Course
from src.models.learning import Enrolment

DEMO_TENANT = uuid.UUID("019fe2ab-dab6-7bea-8f14-d3ea786a227d")
DEMO_USER = uuid.UUID("01a00b9e-6740-7186-a580-b511f63d1955")
DEFAULT_SLUG = "leading-through-ambiguity"


async def main() -> None:
    slug = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SLUG
    settings = get_settings()
    if settings.environment not in ("local", "development", "dev"):
        raise SystemExit(f"refusing to run in ENVIRONMENT={settings.environment!r}")

    init_engine(settings)
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        await set_tenant(session, DEMO_TENANT)

        course = (
            await session.execute(select(Course).where(Course.slug == slug))
        ).scalar_one_or_none()
        if course is None:
            raise SystemExit(f"no course with slug {slug!r} — run seed_demo_content.py first")

        existing = (
            await session.execute(
                select(Enrolment).where(
                    Enrolment.user_id == DEMO_USER, Enrolment.course_id == course.id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            print(f"already enrolled in {slug} (enrolment {existing.id})")
            return

        entitlement = Entitlement(
            id=uuid7(),
            tenant_id=DEMO_TENANT,
            user_id=DEMO_USER,
            kind="course",
            target_id=course.id,
        )
        session.add(entitlement)
        await session.flush()

        enrolment = Enrolment(
            id=uuid7(),
            tenant_id=DEMO_TENANT,
            user_id=DEMO_USER,
            course_id=course.id,
            entitlement_id=entitlement.id,
        )
        session.add(enrolment)
        await session.flush()
        print(f"enrolled in {slug} — enrolment {enrolment.id}")


asyncio.run(main())
