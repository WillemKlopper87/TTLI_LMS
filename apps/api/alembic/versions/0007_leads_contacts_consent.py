"""Phase 2 foundation: contacts, leads, consent_records.

Scoped deliberately narrow. 02 §10 names the full CRM (`leads`, `contacts`,
`deals`, `tasks`, `notes`, `activities`, `campaigns`, `segments`,
`email_templates`, `email_sends`, `email_events`, `suppressions`) but that is
Phase 5 marketing-automation surface. This migration builds only what
`POST /leads` (03 §4.1) needs to function: `contacts` (encrypted PII, same
pattern as `users`), `leads` (the UTM quintet, source, score, stage, and the
REQ-LEAD-02 progressive-profiling fields — updated in place across repeat
submissions, not duplicated), and `consent_records` (append-only, same
two-layer enforcement as `audit_events`: no UPDATE/DELETE grant, plus a
raising trigger).

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = ("contacts", "leads", "consent_records")
APPEND_ONLY = ("consent_records",)


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("email_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("email_blind_index", sa.LargeBinary(), nullable=False),
        sa.Column("email_domain", pg.CITEXT(), nullable=False),
        sa.Column("first_name_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("last_name_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_contacts_tenant_id", "contacts", ["tenant_id"])
    op.create_index("ix_contacts_email_domain", "contacts", ["email_domain"])
    # Unique per tenant, not globally — same reasoning as users: the same
    # person may be a lead with two different corporate customers.
    op.create_index(
        "uq_contacts_tenant_email", "contacts", ["tenant_id", "email_blind_index"], unique=True
    )

    op.create_table(
        "leads",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stage", sa.String(32), nullable=False, server_default="new"),
        # REQ-LEAD-02 progressive profiling — filled in across repeat
        # submissions from the same contact, never overwritten with a null.
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("job_title", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("team_size", sa.Text(), nullable=True),
        sa.Column("training_goal", sa.Text(), nullable=True),
        sa.Column("budget", sa.Text(), nullable=True),
        sa.Column("timeline", sa.Text(), nullable=True),
        # REQ-LEAD-03
        sa.Column("utm_source", sa.Text(), nullable=True),
        sa.Column("utm_medium", sa.Text(), nullable=True),
        sa.Column("utm_campaign", sa.Text(), nullable=True),
        sa.Column("utm_content", sa.Text(), nullable=True),
        sa.Column("utm_term", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_leads_tenant_id", "leads", ["tenant_id"])
    op.create_index("uq_leads_tenant_contact", "leads", ["tenant_id", "contact_id"], unique=True)

    op.create_table(
        "consent_records",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Exactly one of these two is set — a consent event belongs to a
        # known user or to a not-yet-registered contact, never neither.
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("ip", pg.INET(), nullable=True),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_consent_records_tenant_id", "consent_records", ["tenant_id"])
    op.create_index("ix_consent_records_user_id", "consent_records", ["user_id"])
    op.create_index("ix_consent_records_contact_id", "consent_records", ["contact_id"])
    op.execute(
        """
        ALTER TABLE consent_records ADD CONSTRAINT ck_consent_records_purpose
        CHECK (purpose IN ('marketing', 'analytics', 'ai_processing'))
        """
    )
    op.execute(
        """
        ALTER TABLE consent_records ADD CONSTRAINT ck_consent_records_one_subject
        CHECK ((user_id IS NULL) <> (contact_id IS NULL))
        """
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

    # consent_records: append-only, same two-layer enforcement as
    # audit_events (0001) — no UPDATE/DELETE grant, plus a raising trigger,
    # reusing the refuse_mutation() function 0001 already installed.
    op.execute(
        """
        CREATE TRIGGER consent_records_append_only
        BEFORE UPDATE OR DELETE ON consent_records
        FOR EACH ROW EXECUTE FUNCTION refuse_mutation();
        """
    )

    for table in TENANT_SCOPED:
        if table in APPEND_ONLY:
            op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        else:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS consent_records_append_only ON consent_records")
    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("consent_records")
    op.drop_table("leads")
    op.drop_table("contacts")
