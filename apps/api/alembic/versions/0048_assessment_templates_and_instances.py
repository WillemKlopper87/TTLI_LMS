"""Assessment platform: templates, instances, subjects, and responses
(§2026-09-11-assessment-platform-design.md §3).

Assessment templates are sellable B2B products: org surveys, 360 multi-rater
instruments, individual assessments, and external-instrument records. Each
template is tenant-owned and versioned. Assessment instances are runs for one
organisation, carrying a snapshot of the template's questions (editable in draft,
frozen on open). Subjects are the people being assessed (multi_rater, individual,
external_instrument only; org_survey has no subjects). Invitations carry invite
tokens and respondent metadata. Responses are anonymous or identified answers.

All tables carry tenant_id for RLS isolation. Pre/post pairing reuses the
`surveys` pattern (same CHECK and partial unique indexes).

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = (
    "assessment_templates",
    "assessment_template_questions",
    "assessment_instances",
    "assessment_subjects",
    "assessment_invitations",
    "assessment_responses",
    "assessment_subject_results",
)


def upgrade() -> None:
    # assessment_templates: tenant-owned product definition
    op.create_table(
        "assessment_templates",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "kind",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'org_survey'"),
        ),
        sa.Column("rater_groups", pg.JSONB(), nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("vendor", sa.String(64), nullable=True),
        sa.Column(
            "response_mode",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'identified'"),
        ),
        sa.Column("minimum_group_size", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("price_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("sections", pg.JSONB(), nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "slug", "version", name="uq_templates_tenant_slug_version"
        ),
    )
    op.create_index("ix_assessment_templates_tenant_id", "assessment_templates", ["tenant_id"])

    # assessment_template_questions: frozen per template version
    op.create_table(
        "assessment_template_questions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assessment_templates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("section_key", sa.String(64), nullable=True),
        sa.Column("question_type", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("scoring", pg.JSONB(), nullable=True),
    )

    # assessment_instances: one run for one organisation
    op.create_table(
        "assessment_instances",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assessment_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column(
            "organisation_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "evaluation_role",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'standalone'"),
        ),
        sa.Column("pair_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("levels_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "question_snapshot", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(evaluation_role = 'standalone' AND pair_id IS NULL) OR "
            "(evaluation_role IN ('pre', 'post') AND pair_id IS NOT NULL)",
            name="ck_assessment_instances_evaluation_pair",
        ),
        sa.Index(
            "uq_assessment_instances_pair_pre",
            "pair_id",
            unique=True,
            postgresql_where=sa.text("evaluation_role = 'pre'"),
        ),
        sa.Index(
            "uq_assessment_instances_pair_post",
            "pair_id",
            unique=True,
            postgresql_where=sa.text("evaluation_role = 'post'"),
        ),
    )
    op.create_index("ix_assessment_instances_tenant_id", "assessment_instances", ["tenant_id"])
    op.create_index(
        "ix_assessment_instances_organisation_id", "assessment_instances", ["organisation_id"]
    )
    op.create_index("ix_assessment_instances_template_id", "assessment_instances", ["template_id"])

    # assessment_subjects: multi_rater, individual, external_instrument
    op.create_table(
        "assessment_subjects",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "instance_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assessment_instances.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("name_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("email_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("role_label", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # assessment_invitations: invite tokens and respondent metadata
    op.create_table(
        "assessment_invitations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "instance_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assessment_instances.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "subject_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assessment_subjects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("rater_group", sa.String(32), nullable=True),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("email_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("level", sa.String(32), nullable=True),
        sa.Column("role_label", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    # assessment_responses: answers to survey/assessment questions
    op.create_table(
        "assessment_responses",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "instance_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assessment_instances.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("invitation_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("rater_group", sa.String(32), nullable=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("respondent_reference", sa.LargeBinary(), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("level", sa.String(32), nullable=True),
        sa.Column("role_label", sa.String(255), nullable=True),
        sa.Column("answers", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(user_id IS NULL) <> (respondent_reference IS NULL)",
            name="ck_assessment_responses_one_subject",
        ),
        sa.UniqueConstraint(
            "instance_id", "invitation_id", name="uq_responses_instance_invitation"
        ),
    )
    op.create_index("ix_assessment_responses_tenant_id", "assessment_responses", ["tenant_id"])
    op.create_index("ix_assessment_responses_instance_id", "assessment_responses", ["instance_id"])

    # assessment_subject_results: external_instrument only
    op.create_table(
        "assessment_subject_results",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assessment_subjects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("administered_by_user_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("administered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vendor_reference", sa.String(255), nullable=True),
        sa.Column("scores", pg.JSONB(), nullable=True),
        sa.Column("report_object_key", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Enable RLS and create policies for tenant isolation
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

    # Add permissions if they don't already exist
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO permissions (code, description) VALUES "
            "('assessment:author', 'Create and publish assessment templates') "
            "ON CONFLICT (code) DO NOTHING"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO permissions (code, description) VALUES "
            "('assessment:run', 'Create and manage assessment instances') "
            "ON CONFLICT (code) DO NOTHING"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO permissions (code, description) VALUES "
            "('assessment:analyse', 'View assessment results and analytics') "
            "ON CONFLICT (code) DO NOTHING"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO role_permissions (role_code, permission_code) VALUES "
            "('admin', 'assessment:author'), ('admin', 'assessment:run'), ('admin', 'assessment:analyse'), "
            "('super_admin', 'assessment:author'), ('super_admin', 'assessment:run'), ('super_admin', 'assessment:analyse') "
            "ON CONFLICT (role_code, permission_code) DO NOTHING"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM role_permissions WHERE permission_code LIKE 'assessment:%'"))
    conn.execute(sa.text("DELETE FROM permissions WHERE code LIKE 'assessment:%'"))

    for table in reversed(TENANT_SCOPED):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_table("assessment_subject_results")
    op.drop_table("assessment_responses")
    op.drop_table("assessment_invitations")
    op.drop_table("assessment_subjects")
    op.drop_table("assessment_instances")
    op.drop_table("assessment_template_questions")
    op.drop_table("assessment_templates")
