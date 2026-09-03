"""Catalogue and content (02 §5): courses, modules, lessons.

Deliberately **not** tenant-scoped (02 §1.3): "the global course catalogue
rows that all tenants share." `CourseTenantAssignment` is the join table
that controls which tenant sees which course, and whether it is bespoke to
one tenant — never a duplicated course row. `Product` (services/commerce)
is the sellable wrapper; a course is the learnable thing it grants access
to via `Product.course_id` — one course can sit behind several tenant-
specific bundles at different prices.

`Course.created_by_tenant_id` (0042) is provenance, not scoping — it
records who authored the row so `services/courses.py`'s cross-tenant
authoring boundary can recognise a course as "still mine" without
depending on `CourseTenantAssignment`'s row-level security, which
literally cannot be queried across tenants (see that module's own
docstring). It plays no part in visibility to learners; only
`CourseTenantAssignment` does that.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk

CONTENT_STATE_VALUES = ("draft", "in_review", "approved", "published", "archived")
ACCESS_LEVEL_VALUES = ("public", "gated", "guest", "paid", "corporate")
MANAGER_VISIBILITY_VALUES = ("aggregate_only", "individual_enabled", "disabled")
# 0029 presentation vocabulary — validated at the schema layer
# (schemas/courses.py), stored as plain strings.
COURSE_LEVEL_VALUES = ("introductory", "intermediate", "executive")
COURSE_FORMAT_VALUES = ("self_paced", "blended", "live_cohort")

# create_type=False: the migration creates these Postgres enum types
# explicitly, once — same reasoning as commerce.py's OrderStatus/InvoiceStatus.
ContentState = Enum(*CONTENT_STATE_VALUES, name="content_state", create_type=False)
AccessLevel = Enum(*ACCESS_LEVEL_VALUES, name="access_level", create_type=False)
ManagerVisibility = Enum(*MANAGER_VISIBILITY_VALUES, name="manager_visibility", create_type=False)


class Course(Base, TimestampMixin):
    __tablename__ = "courses"
    __table_args__ = (Index("uq_courses_slug", "slug", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(ContentState, nullable=False, server_default="draft")
    # 0042 (H-12) — the tenant that created this row, used by the
    # cross-tenant authoring boundary (services/courses.py::
    # course_authorable) as the "still mine to work on, regardless of
    # publish/assignment state" signal `course_tenant_assignments`'
    # FORCE RLS can't provide. NULL on every pre-0042 row (nothing
    # recorded this before the column existed); those rows fall back to
    # the assignment-only check, unchanged from before.
    created_by_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # REQ-TEN-03: aggregate-only by default — a course cannot be authored
    # into individual-score visibility, that also needs the tenant-level
    # setting and an explicit permission (04 §2.3), neither of which exist
    # yet (Phase 5). This column is the course-level third of that chain.
    manager_visibility: Mapped[str] = mapped_column(
        ManagerVisibility, nullable=False, server_default="aggregate_only"
    )
    # 02 §5.2 shape, validated by CompletionRules (services/completion.py)
    # on write. The course-level default; a lesson's own completion_rules
    # overrides per-field, never wholesale (services/completion.py.merge).
    completion_rules: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    # Phase 4 sprint 4 — nullable since not every course certifies or
    # badges completion; deferred from 0011 because the target tables
    # didn't exist yet.
    certificate_template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("certificate_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    badge_template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("badge_templates.id", ondelete="SET NULL"), nullable=True
    )
    # 0029 — presentation metadata for the public catalogue / landing /
    # learner dashboard (the approved prototype). All optional; the
    # public course surface (`routers/courses.py`) reads them, nothing
    # else does. Plain strings rather than enums for the same reason
    # `Lesson.activity_type` is (this set is a UI vocabulary, not a
    # state machine).
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(64), nullable=True)
    format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    outcomes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    includes_workshop: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    hero_colour: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 0040 — the course-level tier of the tenant->course->per-upload video
    # settings chain: {rungs: [...], allow_bypass: bool}. Absent keys
    # inherit the tenant default (services/media/video_settings.py),
    # exactly the same "course default, per-item overrides" shape
    # completion_rules already established above.
    video_settings: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )


class Module(Base, TimestampMixin):
    __tablename__ = "modules"
    __table_args__ = (Index("ix_modules_course_position", "course_id", "position"),)

    id: Mapped[uuid.UUID] = pk()
    # No index=True: the composite index below already covers course_id
    # lookups as its leftmost column — a separate single-column index would
    # be redundant (and alembic check flags exactly that mismatch).
    course_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class Lesson(Base, TimestampMixin):
    __tablename__ = "lessons"
    __table_args__ = (Index("ix_lessons_module_position", "module_id", "position"),)

    id: Mapped[uuid.UUID] = pk()
    # No index=True — see Module.course_id above; ix_lessons_module_position
    # already covers module_id as its leftmost column.
    module_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    access_level: Mapped[str] = mapped_column(AccessLevel, nullable=False, server_default="paid")
    # Lesson-level override of the course default (02 §5.2) — absent
    # fields fall through to the course's completion_rules, never a null
    # that silently disables the course-level rule. A lesson's own blocks
    # each carry a further override on top of this one (0041) — three
    # tiers total, same "more specific wins per-field" merge each time.
    # This tier still matters even for a multi-block lesson: rules like
    # minimum_time_seconds apply once per lesson regardless of block count.
    completion_rules: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    # A lesson's content is now an ordered sequence of blocks (0041), not
    # a single activity_type — see LessonBlock below. Fetched via
    # services.lesson_blocks.list_blocks(session, lesson_id=...), the
    # same explicit-query-function shape list_lessons/list_modules
    # already use — this codebase never uses ORM relationship attributes.


BLOCK_TYPE_VALUES = ("text", "video", "audio", "quiz", "survey", "assignment")


class LessonBlock(Base, TimestampMixin):
    """One item in a lesson's ordered content sequence (0041 — replaces
    the old one-activity-per-lesson model: `Lesson.activity_type` plus a
    single nullable FK per type). A lesson can hold any number of blocks
    of any type in any order, e.g. text, then video, then a quiz.

    `Quiz`/`Survey`/`Assignment`/`VideoAsset`/`AudioAsset` remain
    standalone resources with no back-reference to a block or lesson —
    same "the FK points at the resource, never the reverse" shape
    `Lesson`'s own FKs already had, now one level down.
    """

    __tablename__ = "lesson_blocks"
    __table_args__ = (Index("ix_lesson_blocks_lesson_position", "lesson_id", "position"),)

    id: Mapped[uuid.UUID] = pk()
    # No index=True — ix_lesson_blocks_lesson_position already covers
    # lesson_id as its leftmost column.
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # text, video, audio, quiz, survey, assignment — a plain string, not
    # an enum, same reasoning Lesson.activity_type used to carry: a UI
    # vocabulary, not a closed set worth an ALTER TYPE migration to grow.
    block_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Text-block body. Nullable — a video/audio/quiz/survey/assignment
    # block carries its content in that subsystem's own table instead.
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("video_assets.id", ondelete="SET NULL"), nullable=True
    )
    # audio_assets.id for block_type="audio" blocks (0041) — deliberately
    # not a VideoAsset variant: no transcode ladder, no renditions, no
    # delivery_mode, just store-and-serve (see AudioAsset's own docstring).
    audio_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audio_assets.id", ondelete="SET NULL"), nullable=True
    )
    quiz_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="SET NULL"), nullable=True
    )
    survey_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("surveys.id", ondelete="SET NULL"), nullable=True
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assignments.id", ondelete="SET NULL"), nullable=True
    )
    # Block-level override of the lesson's (itself an override of the
    # course's) completion_rules — the third and most specific tier of
    # the same merge idiom. Unused by types with no matching rule (text,
    # audio — see services/completion.py's rule-to-subsystem mapping).
    completion_rules: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )


class CourseTenantAssignment(Base, TimestampMixin):
    """Which tenants may see which courses (02 §5.3) — the course row
    itself is global and never duplicated per tenant."""

    __tablename__ = "course_tenant_assignments"
    __table_args__ = (Index("uq_course_tenant_assignments", "tenant_id", "course_id", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # No index=True: this table is small (one row per tenant per visible
    # course) and the common lookup is by tenant_id, already indexed above.
    course_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    is_bespoke: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


__all__ = [
    "BLOCK_TYPE_VALUES",
    "COURSE_FORMAT_VALUES",
    "COURSE_LEVEL_VALUES",
    "AccessLevel",
    "Course",
    "CourseTenantAssignment",
    "Lesson",
    "LessonBlock",
    "ManagerVisibility",
    "Module",
]
