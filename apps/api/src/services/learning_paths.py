"""Learning-path authoring: creating a path, ordering its member courses,
publishing, and assigning it to a tenant (`docs/BACKLOG.md` P5). Mirrors
`services/courses.py`'s shape closely — `LearningPath` is global, not
tenant-scoped (`models/learning_path.py`'s own docstring), and
`LearningPathTenantAssignment` is what makes an authored path visible to
a tenant, exactly as `CourseTenantAssignment` does for a course.

Progress rollup and certificate issuance (Pass E's later phases) live
here too once built — not in `services/enrolment.py`/`services/
credentials.py`, the same "new precedent, own module" reasoning
`services/operations.py`'s docstring already gives for not folding a new
feature into an existing, unrelated file.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.commerce import Price, Product
from src.models.course import Course
from src.models.credential import CertificateTemplate
from src.models.learning_path import (
    LearningPath,
    LearningPathCourse,
    LearningPathTenantAssignment,
)
from src.services.courses import PublicPriceRow

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# A single-course "path" is just the course — the point of the wrapper
# is a sequence, so publishing refuses below this (mirrors courses.py::
# publish_course's own inline blocker checks, not a call into the
# readiness report below: publish stays server-enforced independently of
# what a UI preview shows, the same split readiness-panel.tsx documents
# for the course wizard).
MINIMUM_COURSES_TO_PUBLISH = 2


class LearningPathError(AppError):
    """A refusal in the path-authoring flow — too few courses, an
    unpublished member course, or assigning a draft path to a tenant."""

    code = "LEARNING_PATH_ERROR"


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return slug or "path"


async def _unique_slug(session: AsyncSession, title: str) -> str:
    base = _slugify(title)
    slug = base
    suffix = 2
    while (
        await session.execute(select(LearningPath.id).where(LearningPath.slug == slug))
    ).scalar_one_or_none() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


async def create_learning_path(
    session: AsyncSession, *, title: str, slug: str | None, description: str | None
) -> LearningPath:
    path = LearningPath(
        id=uuid7(),
        slug=slug or await _unique_slug(session, title),
        title=title,
        description=description,
    )
    session.add(path)
    await session.flush()
    return path


async def get_learning_path(session: AsyncSession, *, learning_path_id: uuid.UUID) -> LearningPath:
    path = await session.get(LearningPath, learning_path_id)
    if path is None:
        raise NotFound("No such learning path.")
    return path


async def list_learning_paths(session: AsyncSession) -> list[LearningPath]:
    stmt = select(LearningPath).order_by(LearningPath.title)
    return list((await session.execute(stmt)).scalars().all())


async def update_learning_path(
    session: AsyncSession,
    *,
    learning_path_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    certificate_template_id: uuid.UUID | None = None,
) -> LearningPath:
    path = await get_learning_path(session, learning_path_id=learning_path_id)
    if title is not None:
        path.title = title
    if description is not None:
        path.description = description
    if certificate_template_id is not None:
        if await session.get(CertificateTemplate, certificate_template_id) is None:
            raise NotFound("No such certificate template.")
        path.certificate_template_id = certificate_template_id
    await session.flush()
    return path


async def list_path_courses(
    session: AsyncSession, *, learning_path_id: uuid.UUID
) -> list[tuple[LearningPathCourse, Course]]:
    stmt = (
        select(LearningPathCourse, Course)
        .join(Course, Course.id == LearningPathCourse.course_id)
        .where(LearningPathCourse.learning_path_id == learning_path_id)
        .order_by(LearningPathCourse.position)
    )
    return list((await session.execute(stmt)).tuples().all())


async def add_course_to_path(
    session: AsyncSession, *, learning_path_id: uuid.UUID, course_id: uuid.UUID
) -> LearningPathCourse:
    await get_learning_path(session, learning_path_id=learning_path_id)
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFound("No such course.")
    existing = (
        await session.execute(
            select(LearningPathCourse.id).where(
                LearningPathCourse.learning_path_id == learning_path_id,
                LearningPathCourse.course_id == course_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise LearningPathError("That course is already in this path.")
    position = (
        await session.execute(
            select(func.count())
            .select_from(LearningPathCourse)
            .where(LearningPathCourse.learning_path_id == learning_path_id)
        )
    ).scalar_one()
    member = LearningPathCourse(
        id=uuid7(), learning_path_id=learning_path_id, course_id=course_id, position=position
    )
    session.add(member)
    await session.flush()
    return member


async def remove_course_from_path(
    session: AsyncSession, *, learning_path_id: uuid.UUID, course_id: uuid.UUID
) -> None:
    member = (
        await session.execute(
            select(LearningPathCourse).where(
                LearningPathCourse.learning_path_id == learning_path_id,
                LearningPathCourse.course_id == course_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise NotFound("That course is not in this path.")
    await session.delete(member)
    await session.flush()


def _check_permutation(expected: list[uuid.UUID], given: list[uuid.UUID]) -> None:
    if sorted(expected) != sorted(given) or len(given) != len(set(given)):
        raise LearningPathError(
            f"Reorder must list every member course exactly once — got {len(given)}, "
            f"expected {len(expected)}."
        )


async def reorder_path_courses(
    session: AsyncSession, *, learning_path_id: uuid.UUID, ordered_course_ids: list[uuid.UUID]
) -> list[tuple[LearningPathCourse, Course]]:
    """The whole permutation in one transaction — same reasoning
    `course_wizard.py::reorder_modules` gives for not doing this as
    sequential per-item PATCHes: completion order is `position`, not
    insertion order, so a race here is learner-facing correctness, not
    cosmetics."""
    rows = await list_path_courses(session, learning_path_id=learning_path_id)
    _check_permutation([member.course_id for member, _ in rows], ordered_course_ids)
    by_course_id = {member.course_id: member for member, _ in rows}
    for index, course_id in enumerate(ordered_course_ids):
        by_course_id[course_id].position = index
    await session.flush()
    return await list_path_courses(session, learning_path_id=learning_path_id)


async def publish_learning_path(
    session: AsyncSession, *, learning_path_id: uuid.UUID
) -> LearningPath:
    path = await get_learning_path(session, learning_path_id=learning_path_id)
    members = await list_path_courses(session, learning_path_id=learning_path_id)
    if len(members) < MINIMUM_COURSES_TO_PUBLISH:
        raise LearningPathError(
            f"A learning path needs at least {MINIMUM_COURSES_TO_PUBLISH} courses "
            "before it can be published."
        )
    unpublished = [course.title for _, course in members if course.state != "published"]
    if unpublished:
        raise LearningPathError(
            f"Every member course must be published first: {', '.join(unpublished)}."
        )
    path.state = "published"
    await session.flush()
    return path


async def unpublish_learning_path(
    session: AsyncSession, *, learning_path_id: uuid.UUID
) -> LearningPath:
    path = await get_learning_path(session, learning_path_id=learning_path_id)
    path.state = "draft"
    await session.flush()
    return path


async def assign_path_to_tenant(
    session: AsyncSession, *, learning_path_id: uuid.UUID, tenant_id: uuid.UUID, is_bespoke: bool
) -> LearningPathTenantAssignment:
    path = await get_learning_path(session, learning_path_id=learning_path_id)
    if path.state != "published":
        raise LearningPathError("Only a published learning path may be assigned to a tenant.")

    existing = (
        await session.execute(
            select(LearningPathTenantAssignment).where(
                LearningPathTenantAssignment.tenant_id == tenant_id,
                LearningPathTenantAssignment.learning_path_id == learning_path_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.is_bespoke = is_bespoke
        await session.flush()
        return existing

    assignment = LearningPathTenantAssignment(
        id=uuid7(), tenant_id=tenant_id, learning_path_id=learning_path_id, is_bespoke=is_bespoke
    )
    session.add(assignment)
    await session.flush()
    return assignment


async def list_tenant_path_assignments(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[tuple[LearningPathTenantAssignment, LearningPath]]:
    stmt = (
        select(LearningPathTenantAssignment, LearningPath)
        .join(LearningPath, LearningPath.id == LearningPathTenantAssignment.learning_path_id)
        .where(LearningPathTenantAssignment.tenant_id == tenant_id)
        .order_by(LearningPath.title)
    )
    return list((await session.execute(stmt)).tuples().all())


# --- Readiness -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PathReadinessCheck:
    code: str
    level: str  # "blocker" | "warning"
    ok: bool
    message: str


@dataclass(frozen=True, slots=True)
class PathReadiness:
    checks: list[PathReadinessCheck]
    publishable: bool
    course_count: int


async def get_path_readiness(
    session: AsyncSession, *, learning_path_id: uuid.UUID
) -> PathReadiness:
    """The same truth `publish_learning_path` enforces, made visible
    before the button — same relationship `course_wizard.py::
    get_readiness` has to `courses.py::publish_course`. This is its own
    function, not a generalisation of the course one: a path's checks
    are structurally different (membership and member-state, not
    content/rules)."""
    path = await get_learning_path(session, learning_path_id=learning_path_id)
    members = await list_path_courses(session, learning_path_id=learning_path_id)
    checks: list[PathReadinessCheck] = []

    def add(code: str, level: str, ok: bool, message: str) -> None:
        checks.append(PathReadinessCheck(code=code, level=level, ok=ok, message=message))

    add(
        "has_courses",
        "blocker",
        len(members) >= MINIMUM_COURSES_TO_PUBLISH,
        f"At least {MINIMUM_COURSES_TO_PUBLISH} member courses"
        if len(members) >= MINIMUM_COURSES_TO_PUBLISH
        else f"Only {len(members)} course(s) — a path needs at least {MINIMUM_COURSES_TO_PUBLISH}.",
    )
    unpublished = [course.title for _, course in members if course.state != "published"]
    add(
        "member_courses_published",
        "blocker",
        not unpublished,
        "Every member course is published"
        if not unpublished
        else f"Not yet published: {', '.join(unpublished)}.",
    )
    add(
        "has_certificate",
        "warning",
        path.certificate_template_id is not None,
        "A certificate template is attached"
        if path.certificate_template_id
        else "No certificate template — learners get no credential on completion.",
    )

    blockers = [c for c in checks if c.level == "blocker"]
    return PathReadiness(
        checks=checks, publishable=all(c.ok for c in blockers), course_count=len(members)
    )


# --- Public browsing (Phase 2) ----------------------------------------


async def _visible_path(
    session: AsyncSession, *, tenant_id: uuid.UUID, learning_path_id: uuid.UUID
) -> LearningPath:
    """A published path this tenant has actually been assigned — the
    path equivalent of `services/courses.py::_visible_course`, same
    visibility rule, same unauthenticated use (the public detail page)."""
    stmt = (
        select(LearningPath)
        .join(
            LearningPathTenantAssignment,
            LearningPathTenantAssignment.learning_path_id == LearningPath.id,
        )
        .where(
            LearningPath.id == learning_path_id,
            LearningPath.state == "published",
            LearningPathTenantAssignment.tenant_id == tenant_id,
        )
    )
    path = (await session.execute(stmt)).scalars().first()
    if path is None:
        raise NotFound("No such learning path.")
    return path


async def list_public_paths(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[LearningPath]:
    """Every published path assigned to this tenant — the anonymous
    catalogue/landing grid (`GET /public/learning-paths`). Same
    visibility rule as `_visible_path`, just as a list."""
    stmt = (
        select(LearningPath)
        .join(
            LearningPathTenantAssignment,
            LearningPathTenantAssignment.learning_path_id == LearningPath.id,
        )
        .where(
            LearningPath.state == "published", LearningPathTenantAssignment.tenant_id == tenant_id
        )
        .order_by(LearningPath.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_public_path(
    session: AsyncSession, *, tenant_id: uuid.UUID, learning_path_id: uuid.UUID
) -> tuple[LearningPath, list[tuple[LearningPathCourse, Course]]]:
    path = await _visible_path(session, tenant_id=tenant_id, learning_path_id=learning_path_id)
    members = await list_path_courses(session, learning_path_id=path.id)
    return path, members


async def public_prices_for_paths(
    session: AsyncSession, *, tenant_id: uuid.UUID, path_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PublicPriceRow]:
    """The path equivalent of `services/courses.py::public_prices_for_
    courses` — same "first active, currently-valid-priced product of
    this tenant" rule, reusing that function's own `PublicPriceRow`
    shape rather than a duplicate."""
    if not path_ids:
        return {}
    now = datetime.now(UTC)
    stmt = (
        select(Product, Price)
        .join(Price, Price.product_id == Product.id)
        .where(
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
            Product.learning_path_id.in_(path_ids),
            or_(Price.valid_until.is_(None), Price.valid_until > now),
        )
        .order_by(Product.name, Price.valid_from)
    )
    result: dict[uuid.UUID, PublicPriceRow] = {}
    for product, price in (await session.execute(stmt)).tuples().all():
        if product.learning_path_id is None or product.learning_path_id in result:
            continue
        result[product.learning_path_id] = PublicPriceRow(
            product_id=product.id,
            price_id=price.id,
            currency=price.currency,
            unit_amount=str(price.unit_amount),
            tax_behaviour=price.tax_behaviour,
            includes_vat=price.tax_behaviour == "inclusive",
        )
    return result


__all__ = [
    "MINIMUM_COURSES_TO_PUBLISH",
    "LearningPathError",
    "PathReadiness",
    "PathReadinessCheck",
    "add_course_to_path",
    "assign_path_to_tenant",
    "create_learning_path",
    "get_learning_path",
    "get_path_readiness",
    "get_public_path",
    "list_learning_paths",
    "list_path_courses",
    "list_public_paths",
    "list_tenant_path_assignments",
    "public_prices_for_paths",
    "publish_learning_path",
    "remove_course_from_path",
    "reorder_path_courses",
    "unpublish_learning_path",
    "update_learning_path",
]
