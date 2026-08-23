"""Learning paths (`docs/BACKLOG.md` P5; `docs/research/enterprise-gaps-
plan.md` Pass E, feature-matrix gap #7) — an ordered bundle of existing
courses, sellable as one product, whose progress is a rollup of its
member courses' progress and which issues its own certificate on
completion.

`learning_paths`/`learning_path_courses` are deliberately **not**
tenant-scoped, the same split `0011`'s own docstring drew for
`courses`/`modules`/`lessons`: "the global course catalogue rows that
all tenants share." `learning_path_tenant_assignments` is what makes an
authored path visible to a given tenant — structurally identical to
`course_tenant_assignments`, RLS included.

`products.learning_path_id` mirrors `products.subscription_plan_id`'s
exact nullable-bridge pattern (`0021`): a product is sellable, a path is
learnable, and `Product.kind` is a plain unconstrained string (no CHECK,
no enum) — `"path"` needs no separate migration to become a legal value,
same as how `"subscription"` was added.

`path_enrolments` mirrors `enrolments` (`0011`): a path has no
`Enrolment` row of its own (each member course does), so this is the
anchor row a path's progress rollup and its certificate need — nothing
else in the schema can play that role.

`certificates.enrolment_id` becomes nullable, with a new nullable
`path_enrolment_id` and a `CHECK` that exactly one is set. Confirmed
safe to reuse rather than duplicate: nothing else on `Certificate` is
course-specific — `snapshot` already fully denormalises learner name,
title, issuer and CPD points, and the token/QR/revocation/public-verify
machinery reads only `snapshot` and the generic columns. Duplicating
that instead (a `path_certificates` table plus its own token/verify
plumbing) would mean re-securing a token-verification subsystem for no
reason.

Revision ID: 0035
Revises: 0034
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = ("learning_path_tenant_assignments", "path_enrolments")


def upgrade() -> None:
    # postgresql.ENUM, not sa.Enum — matches 0030/0031's own precedent for
    # reusing an already-existing type inline in create_table();
    # create_type=False on a bare sa.Enum does not reliably suppress the
    # CREATE TYPE DDL in this context.
    content_state = pg.ENUM(
        "draft",
        "in_review",
        "approved",
        "published",
        "archived",
        name="content_state",
        create_type=False,
    )

    op.create_table(
        "learning_paths",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("state", content_state, nullable=False, server_default="draft"),
        sa.Column(
            "certificate_template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("certificate_templates.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("uq_learning_paths_slug", "learning_paths", ["slug"], unique=True)

    op.create_table(
        "learning_path_courses",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "learning_path_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("learning_paths.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_learning_path_courses_learning_path_id",
        "learning_path_courses",
        ["learning_path_id"],
    )
    op.create_index(
        "uq_learning_path_courses",
        "learning_path_courses",
        ["learning_path_id", "course_id"],
        unique=True,
    )

    op.create_table(
        "learning_path_tenant_assignments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "learning_path_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("learning_paths.id", ondelete="RESTRICT"),
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
        "ix_learning_path_tenant_assignments_tenant_id",
        "learning_path_tenant_assignments",
        ["tenant_id"],
    )
    op.create_index(
        "uq_learning_path_tenant_assignments",
        "learning_path_tenant_assignments",
        ["tenant_id", "learning_path_id"],
        unique=True,
    )

    op.create_table(
        "path_enrolments",
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
            "learning_path_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("learning_paths.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "entitlement_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("entitlements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_path_enrolments_tenant_id", "path_enrolments", ["tenant_id"])
    op.create_index("ix_path_enrolments_user_id", "path_enrolments", ["user_id"])
    op.create_index(
        "uq_path_enrolments_tenant_user_path",
        "path_enrolments",
        ["tenant_id", "user_id", "learning_path_id"],
        unique=True,
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

    # Global tables, same treatment as courses/modules/lessons — no DELETE
    # on learning_paths (no delete-path endpoint, same as courses); the
    # membership join needs DELETE to remove a course from a path.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON learning_paths TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON learning_path_courses TO {APP_ROLE}")

    op.add_column(
        "products",
        sa.Column(
            "learning_path_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("learning_paths.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )

    # --- certificates: nullable enrolment_id, new path_enrolment_id -----
    op.alter_column("certificates", "enrolment_id", nullable=True)
    op.add_column(
        "certificates",
        sa.Column(
            "path_enrolment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("path_enrolments.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.drop_index("uq_certificates_enrolment", table_name="certificates")
    op.create_index(
        "uq_certificates_enrolment",
        "certificates",
        ["enrolment_id"],
        unique=True,
        postgresql_where=sa.text("enrolment_id IS NOT NULL"),
    )
    op.create_index(
        "uq_certificates_path_enrolment",
        "certificates",
        ["path_enrolment_id"],
        unique=True,
        postgresql_where=sa.text("path_enrolment_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_certificates_exactly_one_enrolment",
        "certificates",
        "(enrolment_id IS NOT NULL) != (path_enrolment_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_certificates_exactly_one_enrolment", "certificates", type_="check")
    op.drop_index("uq_certificates_path_enrolment", table_name="certificates")
    op.drop_index("uq_certificates_enrolment", table_name="certificates")
    op.create_index("uq_certificates_enrolment", "certificates", ["enrolment_id"], unique=True)
    op.drop_column("certificates", "path_enrolment_id")
    op.alter_column("certificates", "enrolment_id", nullable=False)

    op.drop_column("products", "learning_path_id")

    for table in TENANT_SCOPED:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")

    op.drop_table("path_enrolments")
    op.drop_table("learning_path_tenant_assignments")
    op.drop_table("learning_path_courses")
    op.drop_table("learning_paths")
