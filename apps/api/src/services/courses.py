"""Course/module/lesson authoring, and tenant visibility assignment
(02 §5, the Phase 4 authoring gap `docs/STATUS.md` tracked). `Course` is
global, not tenant-scoped (`src/models/course.py`'s own docstring);
`CourseTenantAssignment` is what makes an authored course visible to a
given tenant, and only a published course may be assigned.

A lesson's content lives in `LessonBlock` rows (0041), owned by
`services/lesson_blocks.py` and the quiz/survey/assignment/video/audio
attach endpoints (`src/routers/assessment.py`, `src/routers/media.py`) —
nothing here ever creates or touches a block; a lesson created through
this module starts with none.
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
from src.models.course import Course, CourseTenantAssignment, Lesson, LessonBlock, Module
from src.models.credential import BadgeTemplate, CertificateTemplate
from src.services.completion import CompletionRules

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class CourseAuthoringError(AppError):
    """A refusal in the authoring flow — an empty course can't publish,
    an unpublished course can't be assigned to a tenant, or a
    completion_rules value doesn't validate."""

    code = "COURSE_AUTHORING_ERROR"


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return slug or "course"


async def _unique_slug(session: AsyncSession, title: str) -> str:
    base = _slugify(title)
    slug = base
    suffix = 2
    while (
        await session.execute(select(Course.id).where(Course.slug == slug))
    ).scalar_one_or_none() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


# --- Cross-tenant authoring boundary (H-12) -------------------------------
#
# Course/module/lesson/block/quiz/survey/assignment/asset/template rows are
# global (this module's own docstring), and `CourseTenantAssignment` is the
# only thing that ever makes one of them visible to a particular tenant --
# exactly like `routers/operations.py` already treats the analytics surface
# and `_visible_course` below already treats the public catalogue. Before
# this, every *authoring* read/write skipped that filter entirely and
# authorised on the `course:edit`/`course:publish` permission strings alone,
# which the seeded tenant `admin` role holds unconditionally -- so any
# tenant's admin could read, edit and publish any other tenant's bespoke
# course (quiz answer keys included). The rule below is applied at every
# authoring entry point in this module, `services/course_wizard.py`,
# `services/lesson_blocks.py` and the quiz/survey/assignment/media/
# credentials/learning-path authoring surfaces that reach through them.
#
# `course_tenant_assignments` carries FORCE ROW LEVEL SECURITY (0011): a
# query against it, from *any* tenant's request transaction, physically
# cannot return another tenant's row -- Postgres filters those out before
# this code ever runs, regardless of the WHERE clause written. That rules
# out an "unclaimed = no assignment row exists at all" test (an earlier
# version of this fix tried exactly that, and it silently degenerated to
# "no assignment row visible to *me*" -- true for both a genuinely
# unclaimed course and one bespoke to someone else, which is the one
# distinction that must not collapse). It also rules out treating every
# `draft` course as universally open: the ordinary create -> publish ->
# assign lifecycle leaves a real gap, published but not yet assigned to
# anyone, during which even the authoring tenant itself has no assignment
# row to point to. `Course.created_by_tenant_id` (0042, no RLS -- courses
# are the deliberately-global table this whole boundary exists to guard)
# closes both gaps: it is set once at creation and answered without ever
# needing to see another tenant's row, so it is the primary signal —
# "the tenant that made it always keeps working access." A `draft` row
# from before that column existed is still treated as unclaimed (nothing
# could have assigned it — `assign_course_to_tenant` refuses anything not
# already `published`); anything else with no recorded creator falls back
# to the assignment check alone, exactly the behaviour it already had.


async def course_authorable(
    session: AsyncSession, *, course_id: uuid.UUID, tenant_id: uuid.UUID
) -> bool:
    course = await session.get(Course, course_id)
    if course is None:
        return False
    # Pre-0042 rows (nothing recorded a creator before the column
    # existed) fall through to the assignment-only check below --
    # unchanged from before that migration.
    if course.created_by_tenant_id is not None:
        if course.created_by_tenant_id == tenant_id:
            return True
    elif course.state == "draft":
        # A draft can only ever have been assigned by first publishing
        # it (`assign_course_to_tenant` refuses anything not already
        # `published`), so an unrecorded-creator draft is guaranteed
        # unclaimed -- the one case pre-0042 rows still need to stay
        # authorable while genuinely new.
        return True
    row = (
        await session.execute(
            select(CourseTenantAssignment.id).where(
                CourseTenantAssignment.course_id == course_id,
                CourseTenantAssignment.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def assert_course_authorable(
    session: AsyncSession, *, course_id: uuid.UUID, tenant_id: uuid.UUID
) -> None:
    if not await course_authorable(session, course_id=course_id, tenant_id=tenant_id):
        # NotFound, not Forbidden -- a course this tenant cannot see must
        # read exactly like one that doesn't exist (routers/operations.py's
        # own stance), so this can't be used to probe the global catalogue
        # for which courses exist and what other tenants have.
        raise NotFound("No such course.")


async def assert_any_course_authorable(
    session: AsyncSession, *, course_ids: list[uuid.UUID], tenant_id: uuid.UUID
) -> None:
    """The same boundary, for a global resource (quiz/survey/assignment/
    certificate template/...) reached indirectly through zero or more
    courses. Zero courses reference it -- unclaimed, same as a freshly
    created one, open to any caller who holds the permission. One or more
    do -- visible if *any* of them is: a resource a shared, multi-tenant
    course also uses must stay reachable to every one of those tenants,
    not just whichever claimed a course first."""
    if not course_ids:
        return
    for course_id in course_ids:
        if await course_authorable(session, course_id=course_id, tenant_id=tenant_id):
            return
    raise NotFound("No such resource.")


async def resolve_course_id_for_module(session: AsyncSession, *, module_id: uuid.UUID) -> uuid.UUID:
    module = await session.get(Module, module_id)
    if module is None:
        raise NotFound("No such module.")
    return module.course_id


async def resolve_course_id_for_lesson(session: AsyncSession, *, lesson_id: uuid.UUID) -> uuid.UUID:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise NotFound("No such lesson.")
    return await resolve_course_id_for_module(session, module_id=lesson.module_id)


async def course_ids_for_quiz(session: AsyncSession, *, quiz_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = (
        select(Module.course_id)
        .join(Lesson, Lesson.module_id == Module.id)
        .join(LessonBlock, LessonBlock.lesson_id == Lesson.id)
        .where(LessonBlock.quiz_id == quiz_id)
        .distinct()
    )
    return list((await session.execute(stmt)).scalars())


async def course_ids_for_survey(session: AsyncSession, *, survey_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = (
        select(Module.course_id)
        .join(Lesson, Lesson.module_id == Module.id)
        .join(LessonBlock, LessonBlock.lesson_id == Lesson.id)
        .where(LessonBlock.survey_id == survey_id)
        .distinct()
    )
    return list((await session.execute(stmt)).scalars())


async def course_ids_for_assignment(
    session: AsyncSession, *, assignment_id: uuid.UUID
) -> list[uuid.UUID]:
    stmt = (
        select(Module.course_id)
        .join(Lesson, Lesson.module_id == Module.id)
        .join(LessonBlock, LessonBlock.lesson_id == Lesson.id)
        .where(LessonBlock.assignment_id == assignment_id)
        .distinct()
    )
    return list((await session.execute(stmt)).scalars())


async def course_ids_for_certificate_template(
    session: AsyncSession, *, template_id: uuid.UUID
) -> list[uuid.UUID]:
    stmt = select(Course.id).where(Course.certificate_template_id == template_id)
    return list((await session.execute(stmt)).scalars())


async def course_ids_for_badge_template(
    session: AsyncSession, *, template_id: uuid.UUID
) -> list[uuid.UUID]:
    stmt = select(Course.id).where(Course.badge_template_id == template_id)
    return list((await session.execute(stmt)).scalars())


async def filter_authorable(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    course_ids_by_item: dict[uuid.UUID, list[uuid.UUID]],
) -> set[uuid.UUID]:
    """Batch form of `assert_any_course_authorable`, for filtering a list
    response in one pair of extra queries rather than one per row.
    `course_ids_by_item` maps each candidate row's id to the course(s) it
    is reachable through (empty for an item no course references yet).
    Returns the subset of ids that pass the same rule `course_authorable`
    applies to a single course — see that function's docstring for why
    "created by me" (or a legacy NULL-creator draft) plus "assigned to
    me" is what unclaimed has to mean once `course_tenant_assignments`'
    RLS is accounted for."""
    all_course_ids = {cid for ids in course_ids_by_item.values() for cid in ids}
    ok_course_ids: set[uuid.UUID] = set()
    if all_course_ids:
        mine_or_unclaimed_rows = await session.execute(
            select(Course.id).where(
                Course.id.in_(all_course_ids),
                (Course.created_by_tenant_id == tenant_id)
                | ((Course.created_by_tenant_id.is_(None)) & (Course.state == "draft")),
            )
        )
        ok_course_ids.update(mine_or_unclaimed_rows.scalars())
        assigned_rows = await session.execute(
            select(CourseTenantAssignment.course_id).where(
                CourseTenantAssignment.course_id.in_(all_course_ids),
                CourseTenantAssignment.tenant_id == tenant_id,
            )
        )
        ok_course_ids.update(assigned_rows.scalars())

    def _authorable(course_ids: list[uuid.UUID]) -> bool:
        return not course_ids or any(cid in ok_course_ids for cid in course_ids)

    return {item_id for item_id, cids in course_ids_by_item.items() if _authorable(cids)}


def _validate_completion_rules(rules: dict[str, object]) -> dict[str, object]:
    try:
        CompletionRules.model_validate(rules)
    except Exception as exc:
        raise CourseAuthoringError(f"Invalid completion_rules: {exc}") from exc
    return rules


async def create_course(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    title: str,
    slug: str | None,
    description: str | None,
    completion_rules: dict[str, object],
    summary: str | None = None,
    level: str | None = None,
    topic: str | None = None,
    format: str | None = None,
    outcomes: list[str] | None = None,
    includes_workshop: bool | None = None,
    hero_colour: str | None = None,
) -> Course:
    _validate_completion_rules(completion_rules)
    course = Course(
        id=uuid7(),
        slug=slug or await _unique_slug(session, title),
        title=title,
        description=description,
        completion_rules=completion_rules,
        summary=summary,
        level=level,
        topic=topic,
        format=format,
        outcomes=list(outcomes) if outcomes is not None else [],
        includes_workshop=bool(includes_workshop),
        hero_colour=hero_colour,
        # 0042 (H-12) — recorded so this tenant keeps working access to
        # its own course regardless of publish/assignment state; see
        # `course_authorable`.
        created_by_tenant_id=tenant_id,
    )
    session.add(course)
    await session.flush()
    return course


async def get_course(
    session: AsyncSession, *, course_id: uuid.UUID, tenant_id: uuid.UUID
) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFound("No such course.")
    await assert_course_authorable(session, course_id=course_id, tenant_id=tenant_id)
    return course


async def list_courses(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Course]:
    """Every course this tenant may author: the list twin of
    `course_authorable`'s boundary (H-12), applied here so the list
    itself can't be used to browse another tenant's bespoke titles. See
    that function's own docstring for why "created by me" (or a legacy
    NULL-creator draft) plus "assigned to me" is what unclaimed actually
    has to mean once `course_tenant_assignments`' RLS is accounted for."""
    has_my_assignment = (
        select(CourseTenantAssignment.id)
        .where(
            CourseTenantAssignment.course_id == Course.id,
            CourseTenantAssignment.tenant_id == tenant_id,
        )
        .exists()
    )
    stmt = (
        select(Course)
        .where(
            (Course.created_by_tenant_id == tenant_id)
            | ((Course.created_by_tenant_id.is_(None)) & (Course.state == "draft"))
            | has_my_assignment
        )
        .order_by(Course.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_course(
    session: AsyncSession,
    *,
    course_id: uuid.UUID,
    tenant_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    completion_rules: dict[str, object] | None = None,
    certificate_template_id: uuid.UUID | None = None,
    badge_template_id: uuid.UUID | None = None,
    summary: str | None = None,
    level: str | None = None,
    topic: str | None = None,
    format: str | None = None,
    outcomes: list[str] | None = None,
    includes_workshop: bool | None = None,
    hero_colour: str | None = None,
) -> Course:
    course = await get_course(session, course_id=course_id, tenant_id=tenant_id)
    if title is not None:
        course.title = title
    if description is not None:
        course.description = description
    if summary is not None:
        course.summary = summary
    if level is not None:
        course.level = level
    if topic is not None:
        course.topic = topic
    if format is not None:
        course.format = format
    if outcomes is not None:
        course.outcomes = list(outcomes)
    if includes_workshop is not None:
        course.includes_workshop = includes_workshop
    if hero_colour is not None:
        course.hero_colour = hero_colour
    if completion_rules is not None:
        course.completion_rules = _validate_completion_rules(completion_rules)
    if certificate_template_id is not None:
        if await session.get(CertificateTemplate, certificate_template_id) is None:
            raise NotFound("No such certificate template.")
        # A template already claimed by another tenant's course must not
        # become linkable here -- otherwise linking it to *this* course
        # would make `course_ids_for_certificate_template` treat it as
        # shared with this tenant too, laundering read/edit access to it
        # (the same reference-laundering H-12 closes on quiz/survey/
        # assignment attach).
        existing_cert_course_ids = await course_ids_for_certificate_template(
            session, template_id=certificate_template_id
        )
        await assert_any_course_authorable(
            session, course_ids=existing_cert_course_ids, tenant_id=tenant_id
        )
        course.certificate_template_id = certificate_template_id
    if badge_template_id is not None:
        if await session.get(BadgeTemplate, badge_template_id) is None:
            raise NotFound("No such badge template.")
        existing_badge_course_ids = await course_ids_for_badge_template(
            session, template_id=badge_template_id
        )
        await assert_any_course_authorable(
            session, course_ids=existing_badge_course_ids, tenant_id=tenant_id
        )
        course.badge_template_id = badge_template_id
    await session.flush()
    return course


async def publish_course(
    session: AsyncSession, *, course_id: uuid.UUID, tenant_id: uuid.UUID
) -> Course:
    course = await get_course(session, course_id=course_id, tenant_id=tenant_id)
    modules = await list_modules(session, course_id=course_id, tenant_id=tenant_id)
    if not modules:
        raise CourseAuthoringError("A course needs at least one module before it can be published.")
    for module in modules:
        if not await list_lessons(session, module_id=module.id, tenant_id=tenant_id):
            raise CourseAuthoringError(
                f'Module "{module.title}" has no lessons — every module needs at least one.'
            )
    course.state = "published"
    await session.flush()
    return course


async def unpublish_course(
    session: AsyncSession, *, course_id: uuid.UUID, tenant_id: uuid.UUID
) -> Course:
    course = await get_course(session, course_id=course_id, tenant_id=tenant_id)
    course.state = "draft"
    await session.flush()
    return course


async def create_module(
    session: AsyncSession, *, course_id: uuid.UUID, tenant_id: uuid.UUID, title: str
) -> Module:
    await get_course(session, course_id=course_id, tenant_id=tenant_id)
    position = (
        await session.execute(
            select(func.count()).select_from(Module).where(Module.course_id == course_id)
        )
    ).scalar_one()
    module = Module(id=uuid7(), course_id=course_id, title=title, position=position)
    session.add(module)
    await session.flush()
    return module


async def update_module(
    session: AsyncSession,
    *,
    module_id: uuid.UUID,
    tenant_id: uuid.UUID,
    title: str | None = None,
    position: int | None = None,
) -> Module:
    module = await session.get(Module, module_id)
    if module is None:
        raise NotFound("No such module.")
    await assert_course_authorable(session, course_id=module.course_id, tenant_id=tenant_id)
    if title is not None:
        module.title = title
    if position is not None:
        module.position = position
    await session.flush()
    return module


async def list_modules(
    session: AsyncSession, *, course_id: uuid.UUID, tenant_id: uuid.UUID
) -> list[Module]:
    await assert_course_authorable(session, course_id=course_id, tenant_id=tenant_id)
    stmt = select(Module).where(Module.course_id == course_id).order_by(Module.position)
    return list((await session.execute(stmt)).scalars().all())


async def create_lesson(
    session: AsyncSession,
    *,
    module_id: uuid.UUID,
    tenant_id: uuid.UUID,
    title: str,
    access_level: str = "paid",
    completion_rules: dict[str, object] | None = None,
) -> Lesson:
    """A newly created lesson has zero blocks — content is added via
    `services/lesson_blocks.py::create_block`, not here (0041)."""
    module = await session.get(Module, module_id)
    if module is None:
        raise NotFound("No such module.")
    await assert_course_authorable(session, course_id=module.course_id, tenant_id=tenant_id)
    rules = _validate_completion_rules(completion_rules or {})
    position = (
        await session.execute(
            select(func.count()).select_from(Lesson).where(Lesson.module_id == module_id)
        )
    ).scalar_one()
    lesson = Lesson(
        id=uuid7(),
        module_id=module_id,
        title=title,
        position=position,
        access_level=access_level,
        completion_rules=rules,
    )
    session.add(lesson)
    await session.flush()
    return lesson


async def update_lesson(
    session: AsyncSession,
    *,
    lesson_id: uuid.UUID,
    tenant_id: uuid.UUID,
    title: str | None = None,
    access_level: str | None = None,
    completion_rules: dict[str, object] | None = None,
    position: int | None = None,
) -> Lesson:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise NotFound("No such lesson.")
    course_id = await resolve_course_id_for_module(session, module_id=lesson.module_id)
    await assert_course_authorable(session, course_id=course_id, tenant_id=tenant_id)
    if title is not None:
        lesson.title = title
    if access_level is not None:
        lesson.access_level = access_level
    if completion_rules is not None:
        lesson.completion_rules = _validate_completion_rules(completion_rules)
    if position is not None:
        lesson.position = position
    await session.flush()
    return lesson


async def list_lessons(
    session: AsyncSession, *, module_id: uuid.UUID, tenant_id: uuid.UUID
) -> list[Lesson]:
    course_id = await resolve_course_id_for_module(session, module_id=module_id)
    await assert_course_authorable(session, course_id=course_id, tenant_id=tenant_id)
    stmt = select(Lesson).where(Lesson.module_id == module_id).order_by(Lesson.position)
    return list((await session.execute(stmt)).scalars().all())


async def assign_course_to_tenant(
    session: AsyncSession, *, course_id: uuid.UUID, tenant_id: uuid.UUID, is_bespoke: bool
) -> CourseTenantAssignment:
    """Self-assignment is intentionally *not* gated by whether the course
    is already bespoke to a different tenant. `course_tenant_assignments`
    carries FORCE ROW LEVEL SECURITY (0011): a query run inside tenant
    B's request transaction cannot see tenant A's row at all, bespoke or
    not, so there is no query this function could run to tell "already
    exclusively claimed elsewhere" apart from "unclaimed" — attempting
    that check (an earlier version of this fix did) silently always
    evaluates false, which is worse than no check: it looks like a
    boundary without being one. A course that is already bespoke to one
    tenant is not, in practice, reachable by another (its id is never
    listed or otherwise surfaced to anyone but the assigned tenant once
    `get_course`/`list_courses`/... apply this same boundary), so the
    residual risk is a caller that already knows another tenant's
    course_id out of band — closing that fully needs either a
    SECURITY DEFINER function that can see across tenants for this one
    existence check, or moving tenant-assignment off self-service
    entirely; both are out of scope here and are called out in the
    fix's own report rather than papered over."""
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFound("No such course.")
    if course.state != "published":
        raise CourseAuthoringError("Only a published course may be assigned to a tenant.")

    existing = (
        await session.execute(
            select(CourseTenantAssignment).where(
                CourseTenantAssignment.tenant_id == tenant_id,
                CourseTenantAssignment.course_id == course_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.is_bespoke = is_bespoke
        await session.flush()
        return existing

    assignment = CourseTenantAssignment(
        id=uuid7(), tenant_id=tenant_id, course_id=course_id, is_bespoke=is_bespoke
    )
    session.add(assignment)
    await session.flush()
    return assignment


async def list_tenant_assignments(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[tuple[CourseTenantAssignment, Course]]:
    stmt = (
        select(CourseTenantAssignment, Course)
        .join(Course, Course.id == CourseTenantAssignment.course_id)
        .where(CourseTenantAssignment.tenant_id == tenant_id)
        .order_by(Course.title)
    )
    return list((await session.execute(stmt)).tuples().all())


async def _visible_course(
    session: AsyncSession, *, tenant_id: uuid.UUID, course_id: uuid.UUID
) -> Course:
    """A published course this tenant has actually been assigned — the
    same visibility a learner's own catalogue browsing would respect, just
    without requiring the caller to be logged in yet (REQ-STORE-05's
    unauthenticated curriculum-outline surface)."""
    stmt = (
        select(Course)
        .join(CourseTenantAssignment, CourseTenantAssignment.course_id == Course.id)
        .where(
            Course.id == course_id,
            Course.state == "published",
            CourseTenantAssignment.tenant_id == tenant_id,
        )
    )
    course = (await session.execute(stmt)).scalars().first()
    if course is None:
        raise NotFound("No such course.")
    return course


async def get_public_curriculum(
    session: AsyncSession, *, tenant_id: uuid.UUID, course_id: uuid.UUID
) -> tuple[Course, list[tuple[Module, list[Lesson]]]]:
    """No lesson `body`/activity FKs — an anonymous visitor sees the shape
    of a course (what modules and lessons exist, and which are free
    previews via `access_level`), never content that isn't actually
    public (that's `get_public_lesson_preview`'s job, gated per-lesson)."""
    course = await _visible_course(session, tenant_id=tenant_id, course_id=course_id)
    modules = await list_modules(session, course_id=course_id)
    result: list[tuple[Module, list[Lesson]]] = []
    for module in modules:
        result.append((module, await list_lessons(session, module_id=module.id)))
    return course, result


async def list_public_courses(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Course]:
    """Every published course assigned to this tenant — the anonymous
    catalogue / landing grid (`GET /public/courses`). The same visibility
    rule as `_visible_course`, just as a list."""
    stmt = (
        select(Course)
        .join(CourseTenantAssignment, CourseTenantAssignment.course_id == Course.id)
        .where(Course.state == "published", CourseTenantAssignment.tenant_id == tenant_id)
        .order_by(Course.title)
    )
    return list((await session.execute(stmt)).scalars().all())


@dataclass(frozen=True, slots=True)
class PublicPriceRow:
    product_id: uuid.UUID
    price_id: uuid.UUID
    currency: str
    unit_amount: str
    tax_behaviour: str
    includes_vat: bool


async def public_prices_for_courses(
    session: AsyncSession, *, tenant_id: uuid.UUID, course_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PublicPriceRow]:
    """For each course, the first ACTIVE product of *this* tenant that
    sells it and has a currently valid price — what the catalogue card
    shows. Courses with no sellable product are simply absent from the
    result (the card renders no price). Which product/price is "first"
    is deterministic (product name, then price valid_from) so the same
    course always shows the same figure."""
    if not course_ids:
        return {}
    now = datetime.now(UTC)
    stmt = (
        select(Product, Price)
        .join(Price, Price.product_id == Product.id)
        .where(
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
            Product.course_id.in_(course_ids),
            or_(Price.valid_until.is_(None), Price.valid_until > now),
        )
        .order_by(Product.name, Price.valid_from)
    )
    result: dict[uuid.UUID, PublicPriceRow] = {}
    for product, price in (await session.execute(stmt)).tuples().all():
        if product.course_id is None or product.course_id in result:
            continue
        result[product.course_id] = PublicPriceRow(
            product_id=product.id,
            price_id=price.id,
            currency=price.currency,
            unit_amount=str(price.unit_amount),
            tax_behaviour=price.tax_behaviour,
            includes_vat=price.tax_behaviour == "inclusive",
        )
    return result


async def cpd_points_for_courses(
    session: AsyncSession, *, courses: list[Course]
) -> dict[uuid.UUID, int | None]:
    """course_id -> the certificate template's cpd_points, for courses
    that certify completion (`certificate_template_id` set)."""
    template_ids = {c.certificate_template_id for c in courses if c.certificate_template_id}
    if not template_ids:
        return {}
    rows = (
        await session.execute(
            select(CertificateTemplate.id, CertificateTemplate.cpd_points).where(
                CertificateTemplate.id.in_(template_ids)
            )
        )
    ).all()
    by_template = {row[0]: row[1] for row in rows}
    return {
        c.id: by_template.get(c.certificate_template_id)
        for c in courses
        if c.certificate_template_id
    }


async def get_public_lesson_preview(
    session: AsyncSession, *, tenant_id: uuid.UUID, lesson_id: uuid.UUID
) -> Lesson:
    stmt = (
        select(Lesson)
        .join(Module, Module.id == Lesson.module_id)
        .join(Course, Course.id == Module.course_id)
        .join(CourseTenantAssignment, CourseTenantAssignment.course_id == Course.id)
        .where(
            Lesson.id == lesson_id,
            Lesson.access_level == "public",
            Course.state == "published",
            CourseTenantAssignment.tenant_id == tenant_id,
        )
    )
    lesson = (await session.execute(stmt)).scalars().first()
    if lesson is None:
        raise NotFound("No such preview lesson.")
    return lesson


__all__ = [
    "CourseAuthoringError",
    "PublicPriceRow",
    "assert_any_course_authorable",
    "assert_course_authorable",
    "assign_course_to_tenant",
    "course_authorable",
    "course_ids_for_assignment",
    "course_ids_for_badge_template",
    "course_ids_for_certificate_template",
    "course_ids_for_quiz",
    "course_ids_for_survey",
    "cpd_points_for_courses",
    "create_course",
    "create_lesson",
    "create_module",
    "filter_authorable",
    "get_course",
    "get_public_curriculum",
    "get_public_lesson_preview",
    "list_courses",
    "list_lessons",
    "list_modules",
    "list_public_courses",
    "list_tenant_assignments",
    "public_prices_for_courses",
    "publish_course",
    "resolve_course_id_for_lesson",
    "resolve_course_id_for_module",
    "unpublish_course",
    "update_course",
    "update_lesson",
    "update_module",
]
