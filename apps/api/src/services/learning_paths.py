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

from src.core.crypto import CryptoBox
from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.commerce import Price, Product
from src.models.course import Course
from src.models.credential import CertificateTemplate
from src.models.learning import Enrolment
from src.models.learning_path import (
    LearningPath,
    LearningPathCourse,
    LearningPathTenantAssignment,
    PathEnrolment,
)
from src.services import enrolment as enrolment_service
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


# --- Progress rollup and completion (Phase 3) ---------------------------


@dataclass(frozen=True, slots=True)
class OwnPathEnrolmentRow:
    path_enrolment_id: uuid.UUID
    learning_path_id: uuid.UUID
    learning_path_title: str
    course_count: int
    started_at: datetime
    completed_at: datetime | None


async def list_own_path_enrolments(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> list[OwnPathEnrolmentRow]:
    """Lightweight metadata only, no progress percentage — same split
    `enrolment_service.list_own_enrolments`/`GET /enrolments` already
    draws against `GET /enrolments/{id}/progress`: a list is a fast
    overview, per-item percent is its own, heavier call."""
    stmt = (
        select(PathEnrolment, LearningPath)
        .join(LearningPath, LearningPath.id == PathEnrolment.learning_path_id)
        .where(PathEnrolment.tenant_id == tenant_id, PathEnrolment.user_id == user_id)
        .order_by(PathEnrolment.started_at.desc())
    )
    rows = (await session.execute(stmt)).tuples().all()
    if not rows:
        return []
    counts_stmt = (
        select(LearningPathCourse.learning_path_id, func.count())
        .where(
            LearningPathCourse.learning_path_id.in_(
                [path_enrolment.learning_path_id for path_enrolment, _ in rows]
            )
        )
        .group_by(LearningPathCourse.learning_path_id)
    )
    counts = dict((await session.execute(counts_stmt)).tuples().all())
    return [
        OwnPathEnrolmentRow(
            path_enrolment_id=path_enrolment.id,
            learning_path_id=path.id,
            learning_path_title=path.title,
            course_count=counts.get(path.id, 0),
            started_at=path_enrolment.started_at,
            completed_at=path_enrolment.completed_at,
        )
        for path_enrolment, path in rows
    ]


@dataclass(frozen=True, slots=True)
class PathCourseProgress:
    course_id: uuid.UUID
    course_title: str
    enrolment_id: uuid.UUID
    progress_percent: int
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PathProgress:
    path_enrolment_id: uuid.UUID
    learning_path_id: uuid.UUID
    progress_percent: int
    completed_at: datetime | None
    courses: list[PathCourseProgress]


async def get_path_progress(
    session: AsyncSession,
    crypto: CryptoBox,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    path_enrolment_id: uuid.UUID,
) -> PathProgress:
    """Rolls up each member course's own progress — computed by
    `enrolment_service.get_progress`, the one place the completion rule
    engine's percent-complete is derived, reused unchanged rather than a
    second, subtly different derivation (that function's own docstring
    gives the same reasoning). `progress_percent` here is the equal-
    weight average of the member percentages — one level up from how a
    course's own percentage is already "completed lessons / total
    lessons", not a distinct rollup semantic."""
    path_enrolment = await session.get(PathEnrolment, path_enrolment_id)
    if (
        path_enrolment is None
        or path_enrolment.tenant_id != tenant_id
        or path_enrolment.user_id != user_id
    ):
        raise NotFound("No such path enrolment.")

    members = await list_path_courses(session, learning_path_id=path_enrolment.learning_path_id)
    courses: list[PathCourseProgress] = []
    for _member, course in members:
        enrolment = await enrolment_service.get_own_enrolment(
            session, tenant_id=tenant_id, user_id=user_id, course_id=course.id
        )
        progress = await enrolment_service.get_progress(
            session,
            crypto,
            tenant_id=tenant_id,
            user_id=user_id,
            enrolment_id=enrolment.id,
        )
        courses.append(
            PathCourseProgress(
                course_id=course.id,
                course_title=course.title,
                enrolment_id=enrolment.id,
                progress_percent=progress.progress_percent,
                completed_at=enrolment.completed_at,
            )
        )

    overall = round(sum(c.progress_percent for c in courses) / len(courses)) if courses else 0
    return PathProgress(
        path_enrolment_id=path_enrolment.id,
        learning_path_id=path_enrolment.learning_path_id,
        progress_percent=overall,
        completed_at=path_enrolment.completed_at,
        courses=courses,
    )


async def find_path_enrolments_for_course_completion(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, course_id: uuid.UUID
) -> list[PathEnrolment]:
    """Called from `services/enrolment.py::complete_lesson` right after a
    course completes: every not-yet-completed `PathEnrolment` this
    learner holds for a path that includes `course_id`, so the caller can
    check whether *every* member course is now done. Membership lookup
    only — `learning_path_courses` is global, so this needs no RLS-aware
    join beyond the tenant-scoped `path_enrolments` filter."""
    stmt = (
        select(PathEnrolment)
        .join(
            LearningPathCourse,
            LearningPathCourse.learning_path_id == PathEnrolment.learning_path_id,
        )
        .where(
            LearningPathCourse.course_id == course_id,
            PathEnrolment.tenant_id == tenant_id,
            PathEnrolment.user_id == user_id,
            PathEnrolment.completed_at.is_(None),
        )
        .distinct()
    )
    return list((await session.execute(stmt)).scalars().all())


async def all_member_courses_completed(
    session: AsyncSession, *, user_id: uuid.UUID, learning_path_id: uuid.UUID
) -> bool:
    """True if every member course has a completed `Enrolment` for this
    user. Deliberately a raw count comparison, not `get_path_progress`
    (which needs `crypto` and a live entitlement re-check that has no
    place inside the completion transaction itself)."""
    members = await list_path_courses(session, learning_path_id=learning_path_id)
    if not members:
        return False
    course_ids = [course.id for _member, course in members]
    completed_count = (
        await session.execute(
            select(func.count())
            .select_from(Enrolment)
            .where(
                Enrolment.user_id == user_id,
                Enrolment.course_id.in_(course_ids),
                Enrolment.completed_at.is_not(None),
            )
        )
    ).scalar_one()
    return completed_count >= len(course_ids)


__all__ = [
    "MINIMUM_COURSES_TO_PUBLISH",
    "LearningPathError",
    "OwnPathEnrolmentRow",
    "PathCourseProgress",
    "PathProgress",
    "PathReadiness",
    "PathReadinessCheck",
    "add_course_to_path",
    "all_member_courses_completed",
    "assign_path_to_tenant",
    "create_learning_path",
    "find_path_enrolments_for_course_completion",
    "get_learning_path",
    "get_path_progress",
    "get_path_readiness",
    "get_public_path",
    "list_learning_paths",
    "list_own_path_enrolments",
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
