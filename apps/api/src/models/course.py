"""Catalogue and content (02 §5): courses, modules, lessons.

Deliberately **not** tenant-scoped (02 §1.3): "the global course catalogue
rows that all tenants share." `CourseTenantAssignment` is the join table
that controls which tenant sees which course, and whether it is bespoke to
one tenant — never a duplicated course row. `Product` (services/commerce)
is the sellable wrapper; a course is the learnable thing it grants access
to via `Product.course_id` — one course can sit behind several tenant-
specific bundles at different prices.
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
    # REQ-LMS-01: video, document, quiz, survey, assignment, workshop
    # requirement. Only "document" is servable this sprint (no video/quiz/
    # survey/assignment subsystem exists yet — Phase 4 sprints 2/3); a
    # plain string, not an enum, because this set grows with each of those
    # sprints and an ALTER TYPE ... ADD VALUE migration per sprint is more
    # ceremony than the closed-set rationale (02 §3) is worth here.
    activity_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="document"
    )
    access_level: Mapped[str] = mapped_column(AccessLevel, nullable=False, server_default="paid")
    # Document-activity body. Nullable — a video/quiz/survey/assignment
    # lesson carries its content in that subsystem's own table instead.
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # video_assets.id for activity_type="video" lessons (Phase 4 sprint 2).
    video_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("video_assets.id", ondelete="SET NULL"), nullable=True
    )
    # quizzes/surveys/assignments.id for the matching activity_type
    # (Phase 4 sprint 3) — same one-nullable-FK-per-subsystem pattern.
    quiz_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="SET NULL"), nullable=True
    )
    survey_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("surveys.id", ondelete="SET NULL"), nullable=True
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assignments.id", ondelete="SET NULL"), nullable=True
    )
    # Lesson-level override of the course default (02 §5.2) — absent
    # fields fall through to the course's completion_rules, never a null
    # that silently disables the course-level rule.
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
    "COURSE_FORMAT_VALUES",
    "COURSE_LEVEL_VALUES",
    "AccessLevel",
    "Course",
    "CourseTenantAssignment",
    "Lesson",
    "ManagerVisibility",
    "Module",
]
