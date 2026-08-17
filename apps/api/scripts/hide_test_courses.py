"""Hide test-suite course artifacts from the demo tenant's catalogue.

Years of test runs have left ~1,300 published courses named "Catalogue
Test Course <hex>", "Subscription Test Course <hex>" and similar in the
local dev database. They are assigned to the demo tenant, so
`GET /public/courses` returns them and the catalogue is undemoable.

What this does: removes the `course_tenant_assignments` row that makes
each such course *visible to the demo tenant*. That is the narrowest
possible lever —

  * no course, module or lesson is deleted;
  * no order, payment, invoice, entitlement or enrolment is touched
    (they do not depend on the assignment);
  * it is reversible — re-assigning is one INSERT per course, and the
    same matching rules identify the set again.

A course is considered a test artifact only if its title matches one of
TEST_PATTERNS *and* it has no summary/topic (every real programme is
seeded with both by seed_demo_content.py and migration 0029), so a
genuine course can never be caught by a title coincidence.

Dry run by default — prints what it would do and changes nothing:

    apps/api/.venv/Scripts/python.exe scripts/hide_test_courses.py

Apply it:

    apps/api/.venv/Scripts/python.exe scripts/hide_test_courses.py --apply

Local/dev only; refuses to run against a production environment.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, func, select
from src.core.config import get_settings
from src.core.db import get_sessionmaker, init_engine, set_tenant
from src.models.course import Course, CourseTenantAssignment

DEMO_TENANT = uuid.UUID("019fe2ab-dab6-7bea-8f14-d3ea786a227d")

TEST_PATTERNS = [
    "Catalogue Test Course%",
    "Subscription Test Course%",
    "Test Course%",
    "Wizard %",
    "Smoke %",
    "%Test Course %",
]


def _is_artifact(title: str, summary: str | None, topic: str | None) -> bool:
    """Title looks generated AND the course carries none of the editorial
    metadata every real programme has. Both must hold."""
    if summary or topic:
        return False
    lowered = title.lower()
    return "test course" in lowered or lowered.startswith("wizard ") or lowered.startswith("smoke ")


async def main() -> None:
    apply = "--apply" in sys.argv
    settings = get_settings()
    if settings.environment not in ("local", "development", "dev"):
        raise SystemExit(f"refusing to run in ENVIRONMENT={settings.environment!r}")

    init_engine(settings)
    factory = get_sessionmaker()
    async with factory() as session, session.begin():
        await set_tenant(session, DEMO_TENANT)

        total_assigned = (
            await session.execute(
                select(func.count())
                .select_from(CourseTenantAssignment)
                .where(CourseTenantAssignment.tenant_id == DEMO_TENANT)
            )
        ).scalar_one()

        rows = (
            await session.execute(
                select(Course.id, Course.title, Course.summary, Course.topic)
                .join(CourseTenantAssignment, CourseTenantAssignment.course_id == Course.id)
                .where(CourseTenantAssignment.tenant_id == DEMO_TENANT)
            )
        ).all()

        artifacts = [r for r in rows if _is_artifact(r.title, r.summary, r.topic)]
        keep = [r for r in rows if not _is_artifact(r.title, r.summary, r.topic)]

        print(f"assigned to the demo tenant : {total_assigned}")
        print(f"test artifacts to hide      : {len(artifacts)}")
        print(f"courses that stay visible   : {len(keep)}")
        print()
        print("staying visible:")
        for r in sorted(keep, key=lambda r: r.title)[:25]:
            print(f"  - {r.title}")
        if len(keep) > 25:
            print(f"  … and {len(keep) - 25} more")

        if not apply:
            print()
            print("DRY RUN — nothing changed. Re-run with --apply to hide them.")
            return

        await session.execute(
            delete(CourseTenantAssignment).where(
                CourseTenantAssignment.tenant_id == DEMO_TENANT,
                CourseTenantAssignment.course_id.in_([r.id for r in artifacts]),
            )
        )
        print()
        print(f"APPLIED — {len(artifacts)} assignment(s) removed; courses themselves untouched.")


asyncio.run(main())
