"""Phase 4 sprint 1: course/module/lesson content model, the server-side
completion rule engine's tables, and enrolments.

Scoped deliberately, matching Phase 3 sprint 1's precedent: 02 §5/§7
documents the full learning surface (video, quizzes, surveys, assignments,
certificates, badges) but none of the subsystems those need exist yet.
This migration builds the part that does not depend on any of them —
course/module/lesson authoring, `enrolments` sourced from an entitlement,
`lesson_completions` as the authoritative progress record, and a
completion rule engine (`services/completion.py`) that can evaluate
`minimum_time_seconds` for real today and refuses (rather than silently
passing) any rule field whose subsystem — video, quiz, survey, assignment,
live attendance — doesn't exist yet.

`courses`/`modules`/`lessons` are deliberately **not** tenant-scoped
(02 §1.3: "the global course catalogue rows that all tenants share").
`course_tenant_assignments`, `enrolments` and `lesson_completions` are.

Seeds one course ("Executive Leadership Certificate", matching the demo
product name from 0009) with one module and two document-type lessons —
explicitly structural/demo content to exercise the LMS mechanics end to
end, the same "demo product seeded so the EFT purchase path is exercisable"
precedent 0009 already set, not real TTLI curriculum (never provided).
`products.course_id` links both tenants' existing seeded products to it —
the multi-tenant "one course, two tenant-branded bundles at different
prices" shape 02 §6.1 describes.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid7() -> uuid.UUID:
    ms = int(time.time() * 1000)
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6:16] = os.urandom(10)
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(b))


APP_ROLE = "app_user"
TENANT_SCOPED = ("course_tenant_assignments", "enrolments", "lesson_completions")
# No authoring endpoint exists yet — read-only from the app's perspective
# this sprint. A future authoring sprint adds INSERT/UPDATE here.
READ_ONLY = ("courses", "modules", "lessons")

CONTENT_STATE_VALUES = ("draft", "in_review", "approved", "published", "archived")
ACCESS_LEVEL_VALUES = ("public", "gated", "guest", "paid", "corporate")
MANAGER_VISIBILITY_VALUES = ("aggregate_only", "individual_enabled", "disabled")
LESSON_STATE_VALUES = ("locked", "available", "in_progress", "requirements_met", "completed")

SEED_COURSE_SLUG = "executive-leadership-certificate"


def upgrade() -> None:
    content_state = pg.ENUM(*CONTENT_STATE_VALUES, name="content_state", create_type=False)
    access_level = pg.ENUM(*ACCESS_LEVEL_VALUES, name="access_level", create_type=False)
    manager_visibility = pg.ENUM(
        *MANAGER_VISIBILITY_VALUES, name="manager_visibility", create_type=False
    )
    lesson_state = pg.ENUM(*LESSON_STATE_VALUES, name="lesson_state", create_type=False)
    content_state.create(op.get_bind())
    access_level.create(op.get_bind())
    manager_visibility.create(op.get_bind())
    lesson_state.create(op.get_bind())

    op.create_table(
        "courses",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("state", content_state, nullable=False, server_default="draft"),
        sa.Column(
            "manager_visibility",
            manager_visibility,
            nullable=False,
            server_default="aggregate_only",
        ),
        sa.Column(
            "completion_rules", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("uq_courses_slug", "courses", ["slug"], unique=True)

    op.create_table(
        "modules",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_modules_course_position", "modules", ["course_id", "position"])

    op.create_table(
        "lessons",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "module_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("activity_type", sa.String(32), nullable=False, server_default="document"),
        sa.Column("access_level", access_level, nullable=False, server_default="paid"),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "completion_rules", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_lessons_module_position", "lessons", ["module_id", "position"])

    op.create_table(
        "course_tenant_assignments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("is_bespoke", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_course_tenant_assignments_tenant_id", "course_tenant_assignments", ["tenant_id"]
    )
    op.create_index(
        "uq_course_tenant_assignments",
        "course_tenant_assignments",
        ["tenant_id", "course_id"],
        unique=True,
    )

    op.create_table(
        "enrolments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "entitlement_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # No cohort table yet (02 §13) — nullable, un-constrained on purpose.
        sa.Column("cohort_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_enrolments_tenant_id", "enrolments", ["tenant_id"])
    op.create_index("ix_enrolments_user_id", "enrolments", ["user_id"])
    op.create_index("ix_enrolments_course_id", "enrolments", ["course_id"])
    op.create_index(
        "uq_enrolments_tenant_user_course",
        "enrolments",
        ["tenant_id", "user_id", "course_id"],
        unique=True,
    )

    op.create_table(
        "lesson_completions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "enrolment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("enrolments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lesson_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("lessons.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", lesson_state, nullable=False, server_default="in_progress"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accumulated_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "rule_evaluation", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_lesson_completions_tenant_id", "lesson_completions", ["tenant_id"])
    op.create_index("ix_lesson_completions_enrolment_id", "lesson_completions", ["enrolment_id"])
    op.create_index(
        "uq_lesson_completions_enrolment_lesson",
        "lesson_completions",
        ["enrolment_id", "lesson_id"],
        unique=True,
    )

    op.add_column(
        "products",
        sa.Column(
            "course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    for table in TENANT_SCOPED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            """
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")

    for table in READ_ONLY:
        op.execute(f"GRANT SELECT ON {table} TO {APP_ROLE}")

    # Seed: one demo course, structural content to exercise the LMS
    # end to end — explicitly not real TTLI curriculum (0009's precedent).
    # UUID v7, generated in Python (02 §1.1), not gen_random_uuid() — same
    # reasoning and helper as 0009's product/price seed.
    conn = op.get_bind()
    course_id = _uuid7()
    conn.execute(
        sa.text(
            "INSERT INTO courses (id, slug, title, description, state) "
            "VALUES (:id, :slug, "
            "'Executive Leadership Certificate', "
            "'A demo course seeded so the LMS completion path is exercisable end to end.', "
            "'published')"
        ),
        {"id": course_id, "slug": SEED_COURSE_SLUG},
    )

    module_id = _uuid7()
    conn.execute(
        sa.text(
            "INSERT INTO modules (id, course_id, title, position) "
            "VALUES (:id, :c, 'Getting Started', 1)"
        ),
        {"id": module_id, "c": course_id},
    )

    for title, position, min_seconds in (("Welcome", 1, 30), ("Core Concepts", 2, 60)):
        conn.execute(
            sa.text(
                "INSERT INTO lessons "
                "(id, module_id, title, position, activity_type, access_level, body, completion_rules) "
                "VALUES (:id, :m, :title, :position, 'document', 'paid', :body, "
                "CAST(:rules AS JSONB))"
            ),
            {
                "id": _uuid7(),
                "m": module_id,
                "title": title,
                "position": position,
                "body": f"Placeholder document content for the '{title}' lesson.",
                "rules": f'{{"minimum_time_seconds": {min_seconds}}}',
            },
        )

    for slug in ("demo", "acme"):
        tenant_id = conn.execute(
            sa.text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug}
        ).scalar()
        if tenant_id is None:
            continue
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text(
                "INSERT INTO course_tenant_assignments (id, tenant_id, course_id, is_bespoke) "
                "VALUES (:id, :t, :c, false)"
            ),
            {"id": _uuid7(), "t": tenant_id, "c": course_id},
        )
        conn.execute(
            sa.text("UPDATE products SET course_id = :c WHERE tenant_id = :t AND slug = :slug"),
            {"c": course_id, "t": tenant_id, "slug": SEED_COURSE_SLUG},
        )


def downgrade() -> None:
    op.execute("UPDATE products SET course_id = NULL")
    op.drop_column("products", "course_id")
    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("lesson_completions")
    op.drop_table("enrolments")
    op.drop_table("course_tenant_assignments")
    op.drop_table("lessons")
    op.drop_table("modules")
    op.drop_table("courses")
    op.execute("DROP TYPE IF EXISTS lesson_state")
    op.execute("DROP TYPE IF EXISTS manager_visibility")
    op.execute("DROP TYPE IF EXISTS access_level")
    op.execute("DROP TYPE IF EXISTS content_state")
