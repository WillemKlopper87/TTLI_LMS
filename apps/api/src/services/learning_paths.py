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

from src.core.config import Settings
from src.core.crypto import CryptoBox
from src.core.errors import AppError, Forbidden, NotFound
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
from src.services import credentials as credentials_service
from src.services import enrolment as enrolment_service
from src.services.courses import (
    PublicPriceRow,
    assert_any_course_authorable,
    assert_course_authorable,
    course_ids_for_certificate_template,
)
from src.services.storage import StorageService

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


# --- Cross-tenant authoring boundary (H-12) -------------------------------
# The exact `CourseTenantAssignment` rule `services/courses.py` applies,
# mirrored onto `LearningPathTenantAssignment` -- see that module's own
# docstring on the boundary for the full reasoning.


async def path_authorable(
    session: AsyncSession, *, learning_path_id: uuid.UUID, tenant_id: uuid.UUID
) -> bool:
    """`learning_path_tenant_assignments` carries FORCE ROW LEVEL SECURITY
    (0035): a query against it from tenant B's request transaction cannot
    see tenant A's row at all, so "no assignment row visible to me" is
    true for both a genuinely unclaimed path and one bespoke to someone
    else — the one distinction that must not collapse. It also can't
    just fall back to "draft state = unclaimed": the ordinary create ->
    publish -> assign lifecycle leaves a real published-but-unassigned
    window even for the authoring tenant itself. `LearningPath.
    created_by_tenant_id` (0042, no RLS) is the fix — set once at
    creation, readable by every tenant's session, answered without ever
    needing to see another tenant's row (mirrors `services/courses.py::
    course_authorable` exactly; see that function's docstring for the
    full reasoning, including why a pre-0042 NULL-creator row still
    falls back to "draft = unclaimed")."""
    path = await session.get(LearningPath, learning_path_id)
    if path is None:
        return False
    if path.created_by_tenant_id is not None:
        if path.created_by_tenant_id == tenant_id:
            return True
    elif path.state == "draft":
        return True
    row = (
        await session.execute(
            select(LearningPathTenantAssignment.id).where(
                LearningPathTenantAssignment.learning_path_id == learning_path_id,
                LearningPathTenantAssignment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def assert_path_authorable(
    session: AsyncSession, *, learning_path_id: uuid.UUID, tenant_id: uuid.UUID
) -> None:
    if not await path_authorable(session, learning_path_id=learning_path_id, tenant_id=tenant_id):
        raise NotFound("No such learning path.")


async def create_learning_path(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    title: str,
    slug: str | None,
    description: str | None,
) -> LearningPath:
    path = LearningPath(
        id=uuid7(),
        slug=slug or await _unique_slug(session, title),
        title=title,
        description=description,
        # 0042 (H-12) — see `path_authorable`.
        created_by_tenant_id=tenant_id,
    )
    session.add(path)
    await session.flush()
    return path


async def get_learning_path(
    session: AsyncSession, *, learning_path_id: uuid.UUID, tenant_id: uuid.UUID
) -> LearningPath:
    path = await session.get(LearningPath, learning_path_id)
    if path is None:
        raise NotFound("No such learning path.")
    await assert_path_authorable(session, learning_path_id=learning_path_id, tenant_id=tenant_id)
    return path


async def list_learning_paths(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[LearningPath]:
    """The list twin of `path_authorable`'s boundary (H-12); see that
    function's docstring for why "created by me" (or a legacy
    NULL-creator draft) plus "assigned to me" is what unclaimed has to
    mean once `learning_path_tenant_assignments`' RLS is accounted for."""
    has_my_assignment = (
        select(LearningPathTenantAssignment.id)
        .where(
            LearningPathTenantAssignment.learning_path_id == LearningPath.id,
            LearningPathTenantAssignment.tenant_id == tenant_id,
        )
        .exists()
    )
    stmt = (
        select(LearningPath)
        .where(
            (LearningPath.created_by_tenant_id == tenant_id)
            | ((LearningPath.created_by_tenant_id.is_(None)) & (LearningPath.state == "draft"))
            | has_my_assignment
        )
        .order_by(LearningPath.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_learning_path(
    session: AsyncSession,
    *,
    learning_path_id: uuid.UUID,
    tenant_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    certificate_template_id: uuid.UUID | None = None,
) -> LearningPath:
    path = await get_learning_path(session, learning_path_id=learning_path_id, tenant_id=tenant_id)
    if title is not None:
        path.title = title
    if description is not None:
        path.description = description
    if certificate_template_id is not None:
        if await session.get(CertificateTemplate, certificate_template_id) is None:
            raise NotFound("No such certificate template.")
        # Same reference-laundering guard `services/courses.py::
        # update_course` applies to a course's own template fields.
        existing_course_ids = await course_ids_for_certificate_template(
            session, template_id=certificate_template_id
        )
        await assert_any_course_authorable(
            session, course_ids=existing_course_ids, tenant_id=tenant_id
        )
        path.certificate_template_id = certificate_template_id
    await session.flush()
    return path


async def clear_certificate_template(
    session: AsyncSession, *, learning_path_id: uuid.UUID, tenant_id: uuid.UUID
) -> LearningPath:
    """`update_learning_path`'s `None = leave unchanged` PATCH semantics
    have no way to express "set this to null" — a course wizard's own
    `POST /courses/{id}/clear-templates` faces the same gap and solves
    it the same way, a dedicated endpoint rather than overloading PATCH
    (F6, docs/research/p5-review-findings.md; a path has only the one
    nullable FK to manage, not a course's certificate-and-badge pair,
    so this needs no request body at all)."""
    path = await get_learning_path(session, learning_path_id=learning_path_id, tenant_id=tenant_id)
    path.certificate_template_id = None
    await session.flush()
    return path


async def list_path_courses(
    session: AsyncSession, *, learning_path_id: uuid.UUID, tenant_id: uuid.UUID
) -> list[tuple[LearningPathCourse, Course]]:
    await assert_path_authorable(session, learning_path_id=learning_path_id, tenant_id=tenant_id)
    stmt = (
        select(LearningPathCourse, Course)
        .join(Course, Course.id == LearningPathCourse.course_id)
        .where(LearningPathCourse.learning_path_id == learning_path_id)
        .order_by(LearningPathCourse.position)
    )
    return list((await session.execute(stmt)).tuples().all())


async def add_course_to_path(
    session: AsyncSession,
    *,
    learning_path_id: uuid.UUID,
    tenant_id: uuid.UUID,
    course_id: uuid.UUID,
) -> LearningPathCourse:
    path = await get_learning_path(session, learning_path_id=learning_path_id, tenant_id=tenant_id)
    # The course being bundled in must be one this tenant can actually
    # see too -- otherwise a path built to include it would surface
    # another tenant's bespoke course title/summary on this path's own
    # public listing (H-12).
    await assert_course_authorable(session, course_id=course_id, tenant_id=tenant_id)
    if path.state == "published":
        # A learner who already bought this path has no Enrolment for a
        # course added after purchase — get_path_progress would raise
        # Forbidden the moment it tries to look one up, and the path
        # could never complete for them (F2, docs/research/p5-review-
        # findings.md). Unpublish first, edit membership, republish —
        # the same honest workflow publish_learning_path already forces
        # for "every member course must be published".
        raise LearningPathError(
            "Unpublish this path before changing its member courses — "
            "editing a published path's membership breaks existing learners' progress."
        )
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
    # max(position) + 1, not count(*): after a removal mid-list, count()
    # collides with a position already in use (member 3 of 3 removed
    # leaves positions 0/1; count() on the next add is 2, colliding with
    # nothing yet, but remove the *first* of three and count() gives 2
    # again — the same value position 2 already holds) — F6, docs/
    # research/p5-review-findings.md.
    max_position = (
        await session.execute(
            select(func.max(LearningPathCourse.position)).where(
                LearningPathCourse.learning_path_id == learning_path_id
            )
        )
    ).scalar_one()
    position = 0 if max_position is None else max_position + 1
    member = LearningPathCourse(
        id=uuid7(), learning_path_id=learning_path_id, course_id=course_id, position=position
    )
    session.add(member)
    await session.flush()
    return member


async def remove_course_from_path(
    session: AsyncSession,
    *,
    learning_path_id: uuid.UUID,
    tenant_id: uuid.UUID,
    course_id: uuid.UUID,
) -> None:
    path = await get_learning_path(session, learning_path_id=learning_path_id, tenant_id=tenant_id)
    if path.state == "published":
        # Same reasoning as add_course_to_path's guard: removing the
        # only incomplete member of a purchased path leaves no lesson
        # left to trigger complete_lesson's completion check, so
        # completed_at (and the certificate) would never fire.
        raise LearningPathError(
            "Unpublish this path before changing its member courses — "
            "editing a published path's membership breaks existing learners' progress."
        )
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
    session: AsyncSession,
    *,
    learning_path_id: uuid.UUID,
    tenant_id: uuid.UUID,
    ordered_course_ids: list[uuid.UUID],
) -> list[tuple[LearningPathCourse, Course]]:
    """The whole permutation in one transaction — same reasoning
    `course_wizard.py::reorder_modules` gives for not doing this as
    sequential per-item PATCHes: completion order is `position`, not
    insertion order, so a race here is learner-facing correctness, not
    cosmetics."""
    rows = await list_path_courses(session, learning_path_id=learning_path_id, tenant_id=tenant_id)
    _check_permutation([member.course_id for member, _ in rows], ordered_course_ids)
    by_course_id = {member.course_id: member for member, _ in rows}
    for index, course_id in enumerate(ordered_course_ids):
        by_course_id[course_id].position = index
    await session.flush()
    return await list_path_courses(session, learning_path_id=learning_path_id, tenant_id=tenant_id)


async def publish_learning_path(
    session: AsyncSession, *, learning_path_id: uuid.UUID, tenant_id: uuid.UUID
) -> LearningPath:
    path = await get_learning_path(session, learning_path_id=learning_path_id, tenant_id=tenant_id)
    members = await list_path_courses(
        session, learning_path_id=learning_path_id, tenant_id=tenant_id
    )
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
    session: AsyncSession, *, learning_path_id: uuid.UUID, tenant_id: uuid.UUID
) -> LearningPath:
    path = await get_learning_path(session, learning_path_id=learning_path_id, tenant_id=tenant_id)
    path.state = "draft"
    await session.flush()
    return path


async def assign_path_to_tenant(
    session: AsyncSession, *, learning_path_id: uuid.UUID, tenant_id: uuid.UUID, is_bespoke: bool
) -> LearningPathTenantAssignment:
    """Same residual-gap note as `services/courses.py::
    assign_course_to_tenant`: RLS on `learning_path_tenant_assignments`
    means this function cannot see another tenant's row to refuse
    self-assignment onto an already-bespoke path, and a check that
    silently never fires is worse than none — see that function's
    docstring for the full reasoning and the fix's report for the
    residual scope."""
    path = await session.get(LearningPath, learning_path_id)
    if path is None:
        raise NotFound("No such learning path.")
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
    session: AsyncSession, *, learning_path_id: uuid.UUID, tenant_id: uuid.UUID
) -> PathReadiness:
    """The same truth `publish_learning_path` enforces, made visible
    before the button — same relationship `course_wizard.py::
    get_readiness` has to `courses.py::publish_course`. This is its own
    function, not a generalisation of the course one: a path's checks
    are structurally different (membership and member-state, not
    content/rules)."""
    path = await get_learning_path(session, learning_path_id=learning_path_id, tenant_id=tenant_id)
    members = await list_path_courses(
        session, learning_path_id=learning_path_id, tenant_id=tenant_id
    )
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


async def course_counts_for_paths(
    session: AsyncSession, *, path_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """One grouped query for `GET /public/learning-paths`'s card grid,
    not a `list_path_courses` call per path in a loop (F6, docs/
    research/p5-review-findings.md) — the same grouped-count pattern
    `list_own_path_enrolments` already uses ten lines away."""
    if not path_ids:
        return {}
    stmt = (
        select(LearningPathCourse.learning_path_id, func.count())
        .where(LearningPathCourse.learning_path_id.in_(path_ids))
        .group_by(LearningPathCourse.learning_path_id)
    )
    return dict((await session.execute(stmt)).tuples().all())


async def get_public_path(
    session: AsyncSession, *, tenant_id: uuid.UUID, learning_path_id: uuid.UUID
) -> tuple[LearningPath, list[tuple[LearningPathCourse, Course]]]:
    path = await _visible_path(session, tenant_id=tenant_id, learning_path_id=learning_path_id)
    members = await list_path_courses(session, learning_path_id=path.id, tenant_id=tenant_id)
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
    # Whether this path issues a certificate at all — without it, a
    # completed path showing "Certified" is simply wrong (F6, docs/
    # research/p5-review-findings.md); the dashboard uses this to label
    # a completed-but-uncertificated path "Completed" instead.
    has_certificate: bool


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
            has_certificate=path.certificate_template_id is not None,
        )
        for path_enrolment, path in rows
    ]


@dataclass(frozen=True, slots=True)
class PathCourseProgress:
    course_id: uuid.UUID
    course_title: str
    # None when this learner has no reachable enrolment for the course —
    # a course added to the path after purchase, or an expired
    # entitlement (F2, docs/research/p5-review-findings.md). The row
    # still renders, just with no progress and nowhere to "Continue" to.
    enrolment_id: uuid.UUID | None
    progress_percent: int
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class PathProgress:
    path_enrolment_id: uuid.UUID
    learning_path_id: uuid.UUID
    progress_percent: int
    completed_at: datetime | None
    courses: list[PathCourseProgress]


async def _repair_completion_if_all_members_done(
    session: AsyncSession,
    crypto: CryptoBox,
    storage: StorageService,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    path_enrolment: PathEnrolment,
) -> None:
    """F5 (docs/research/p5-review-findings.md): a learner who already
    held every member course before buying the path gets a
    `PathEnrolment` whose completion can never be detected the normal
    way — `services/enrolment.py::complete_lesson`'s hook only runs when
    a lesson actually completes, and there is no lesson left to complete
    for a course finished before the purchase. Checked here, the one
    place this state is guaranteed to be read at least once (a learner
    who buys a path they've already finished has every reason to open
    its progress page), rather than at purchase time — reaching for it
    there would mean threading `storage`/`settings` through the payment-
    approval hot path (`services/orders.py`'s three fulfilment entry
    points) for an edge case this read-repair already covers just as
    correctly, and idempotently (`issue_for_completed_path`'s own
    existing-certificate check makes a second read a no-op)."""
    if path_enrolment.completed_at is not None:
        return
    if not await all_member_courses_completed(
        session,
        tenant_id=tenant_id,
        user_id=path_enrolment.user_id,
        learning_path_id=path_enrolment.learning_path_id,
    ):
        return
    path_enrolment.completed_at = datetime.now(UTC)
    await session.flush()
    path = await session.get(LearningPath, path_enrolment.learning_path_id)
    if path is None:  # pragma: no cover - FK guarantees this
        return
    issued = await credentials_service.issue_for_completed_path(
        session,
        crypto,
        tenant_id=tenant_id,
        path_enrolment=path_enrolment,
        path_title=path.title,
        certificate_template_id=path.certificate_template_id,
    )
    if issued.certificate is not None and issued.raw_verification_token is not None:
        await enrolment_service.persist_certificate_pdf(
            session,
            storage,
            settings,
            tenant_id=tenant_id,
            certificate=issued.certificate,
            raw_verification_token=issued.raw_verification_token,
        )


async def get_path_progress(
    session: AsyncSession,
    crypto: CryptoBox,
    storage: StorageService,
    settings: Settings,
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

    await _repair_completion_if_all_members_done(
        session, crypto, storage, settings, tenant_id=tenant_id, path_enrolment=path_enrolment
    )

    members = await list_path_courses(
        session, learning_path_id=path_enrolment.learning_path_id, tenant_id=tenant_id
    )
    courses: list[PathCourseProgress] = []
    for _member, course in members:
        try:
            enrolment = await enrolment_service.get_own_enrolment(
                session, tenant_id=tenant_id, user_id=user_id, course_id=course.id
            )
        except Forbidden:
            # No reachable enrolment for this member course — it was
            # added to the path after this learner bought it (a
            # published path's membership is meant to be frozen, but a
            # path sold before this guard existed can still be in this
            # state), or the course's own entitlement lapsed. Either way
            # this is a display concern, not a reason to fail the whole
            # rollup for every other course the learner *can* see (F2,
            # docs/research/p5-review-findings.md).
            courses.append(
                PathCourseProgress(
                    course_id=course.id,
                    course_title=course.title,
                    enrolment_id=None,
                    progress_percent=0,
                    completed_at=None,
                )
            )
            continue
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
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, learning_path_id: uuid.UUID
) -> bool:
    """True if every member course has a completed `Enrolment` for this
    user. Deliberately a raw count comparison, not `get_path_progress`
    (which needs `crypto` and a live entitlement re-check that has no
    place inside the completion transaction itself). `tenant_id` is
    filtered explicitly rather than left to RLS alone (F6, docs/
    research/p5-review-findings.md) — every sibling query in this
    module does, and this one is one call away from a completion
    transaction, not a place to be the one exception."""
    members = await list_path_courses(
        session, learning_path_id=learning_path_id, tenant_id=tenant_id
    )
    if not members:
        return False
    course_ids = [course.id for _member, course in members]
    completed_count = (
        await session.execute(
            select(func.count())
            .select_from(Enrolment)
            .where(
                Enrolment.tenant_id == tenant_id,
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
    "clear_certificate_template",
    "course_counts_for_paths",
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
