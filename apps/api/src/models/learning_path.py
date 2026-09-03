"""Learning paths (02 §5-adjacent, `docs/BACKLOG.md` P5) — an ordered
bundle of existing courses. Deliberately **not** tenant-scoped, the same
split `course.py`'s own docstring draws for `courses`/`modules`/
`lessons`: the global rows all tenants share.
`LearningPathTenantAssignment` is what makes an authored path visible to
a given tenant, structurally identical to `CourseTenantAssignment`.

`LearningPath.created_by_tenant_id` (0042) mirrors `Course.created_by_
tenant_id` exactly — see that column's docstring for why it exists
(RLS on the assignment table makes it unqueryable across tenants) and
why it is provenance, not visibility.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, pk
from src.models.course import ContentState


class LearningPath(Base, TimestampMixin):
    __tablename__ = "learning_paths"
    __table_args__ = (Index("uq_learning_paths_slug", "slug", unique=True),)

    id: Mapped[uuid.UUID] = pk()
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(ContentState, nullable=False, server_default="draft")
    certificate_template_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("certificate_templates.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_by_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class LearningPathCourse(Base):
    """Ordered membership — a course may appear in several paths, and a
    path's completion order is `position`, not insertion order."""

    __tablename__ = "learning_path_courses"
    __table_args__ = (
        Index("uq_learning_path_courses", "learning_path_id", "course_id", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    learning_path_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("learning_paths.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class LearningPathTenantAssignment(Base, TimestampMixin):
    """Which tenants may see which paths — mirrors `CourseTenantAssignment`
    exactly; the path row itself is global and never duplicated per tenant."""

    __tablename__ = "learning_path_tenant_assignments"
    __table_args__ = (
        Index("uq_learning_path_tenant_assignments", "tenant_id", "learning_path_id", unique=True),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    learning_path_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("learning_paths.id", ondelete="RESTRICT"), nullable=False
    )
    is_bespoke: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class PathEnrolment(Base, TimestampMixin):
    """Joins a user to a learning path, sourced from a path-kind
    entitlement (`services/orders.py::_fulfil_order`'s path branch) — the
    anchor row a path's progress rollup and its certificate need. A path
    has no `Enrolment` row of its own; only its member courses do."""

    __tablename__ = "path_enrolments"
    __table_args__ = (
        Index(
            "uq_path_enrolments_tenant_user_path",
            "tenant_id",
            "user_id",
            "learning_path_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    learning_path_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("learning_paths.id", ondelete="RESTRICT"), nullable=False
    )
    entitlement_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("entitlements.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "LearningPath",
    "LearningPathCourse",
    "LearningPathTenantAssignment",
    "PathEnrolment",
]
