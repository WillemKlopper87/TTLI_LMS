"""Phase 5 sprint 4: CRM and marketing engine (02 §10, REQ-CRM-01
through REQ-CRM-05 — REQ-CRM-06 through 09 are AI insights, Phase 6,
not here).

Exactly the ten tables 02 §10 already named: `deals`, `tasks`, `notes`,
`activities`, `campaigns`, `segments`, `email_templates`, `email_sends`,
`email_events`, `suppressions`. `leads`/`contacts`/`consent_records`
already existed from Phase 2 — a deal, task and note all hang off a
`contacts` row the funnel already captured, never a duplicated person
record.

Deal-centric shape: `tasks`/`notes` always reference a `deal_id`
(required, not optional) — this is a pipeline-tracking CRM, not a
freeform contact-notes app, and giving every task/note a deal keeps
`activities` (deal-scoped, append-only) a complete audit trail of one
deal's history without a second "which subject type" branch.

`suppressions` keys on `email_blind_index` (never plaintext, 02 §10's
own wording) — the same blind-index mechanism `contacts.email_blind_index`
already uses, so a suppression check never has to decrypt anything.

No ESP provider abstraction here, unlike `0018`'s meeting providers:
`services/email.py`'s real SMTP path (Mailpit locally, any real SMTP
relay in production) already sends both transactional and bulk mail
end to end — there is no second, blocked-on-credentials implementation
to build an interface around. REQ-CRM-03's "SPF/DKIM/DMARC on a
dedicated sending domain" is a DNS/domain-ownership decision, not a
code capability gap; nothing here is blocked on it, the same way
`eft_bank_name` needed a placeholder rather than a provider interface.

Deliberately deferred: open/click tracking (needs an HTML-templated
send with a tracking pixel/link-rewriting; `services/email.py` only
ever sent plain text, a constraint from Phase 2 this sprint doesn't
lift) and campaign scheduling (`campaigns.scheduled_at` exists as a
column but nothing reads it yet — sends are POST-triggered, not
time-triggered, deferred alongside REQ-WS's own "no automated action"
discipline).

Revision ID: 0019
Revises: 0018
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = (
    "deals",
    "tasks",
    "notes",
    "activities",
    "segments",
    "email_templates",
    "campaigns",
    "email_sends",
    "email_events",
    "suppressions",
)
APPEND_ONLY = ("activities", "email_events")

DEAL_STAGE_VALUES = ("new", "qualified", "proposal", "won", "lost")
CAMPAIGN_STATUS_VALUES = ("draft", "sending", "sent")
EMAIL_SEND_STATUS_VALUES = ("queued", "sent", "failed", "suppressed", "bounced")

NEW_PERMISSIONS: list[tuple[str, str]] = [
    ("deal:manage", "Create and manage deals, tasks and notes"),
    ("campaign:manage", "Create segments, templates and campaigns; send campaign email"),
]


def upgrade() -> None:
    bind = op.get_bind()
    deal_stage = sa.Enum(*DEAL_STAGE_VALUES, name="deal_stage")
    campaign_status = sa.Enum(*CAMPAIGN_STATUS_VALUES, name="campaign_status")
    email_send_status = sa.Enum(*EMAIL_SEND_STATUS_VALUES, name="email_send_status")

    op.create_table(
        "deals",
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
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("stage", deal_stage, nullable=False, server_default="new"),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("campaign", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_deals_tenant_id", "deals", ["tenant_id"])
    op.create_index("ix_deals_contact_id", "deals", ["contact_id"])

    op.create_table(
        "tasks",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "deal_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("deals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "assigned_to_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_tasks_tenant_id", "tasks", ["tenant_id"])
    op.create_index("ix_tasks_deal_id", "tasks", ["deal_id"])

    op.create_table(
        "notes",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "deal_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("deals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "author_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_notes_tenant_id", "notes", ["tenant_id"])
    op.create_index("ix_notes_deal_id", "notes", ["deal_id"])

    op.create_table(
        "activities",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "deal_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("deals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("detail", pg.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "actor_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_activities_tenant_id", "activities", ["tenant_id"])
    op.create_index("ix_activities_deal_id", "activities", ["deal_id"])

    op.create_table(
        "segments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        # Criteria over non-PII lead/contact attributes only (stage, UTM
        # quintet) — 02 §10's own resolution of the encrypted-email-vs-
        # bulk-marketing conflict (04 §4.4).
        sa.Column("criteria", pg.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_segments_tenant_id", "segments", ["tenant_id"])

    op.create_table(
        "email_templates",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        # Plain text only — services/email.py has never sent HTML (Phase 2
        # built it that way); this sprint doesn't add a templating engine.
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_email_templates_tenant_id", "email_templates", ["tenant_id"])

    op.create_table(
        "campaigns",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "segment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("segments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", campaign_status, nullable=False, server_default="draft"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_campaigns_tenant_id", "campaigns", ["tenant_id"])

    op.create_table(
        "email_sends",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", email_send_status, nullable=False, server_default="queued"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_email_sends_tenant_id", "email_sends", ["tenant_id"])
    op.create_index("ix_email_sends_campaign_id", "email_sends", ["campaign_id"])
    op.create_index(
        "uq_email_sends_campaign_contact", "email_sends", ["campaign_id", "contact_id"], unique=True
    )

    op.create_table(
        "email_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "email_send_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("email_sends.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("detail", pg.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('bounced', 'unsubscribed')", name="ck_email_events_kind"),
    )
    op.create_index("ix_email_events_tenant_id", "email_events", ["tenant_id"])
    op.create_index("ix_email_events_email_send_id", "email_events", ["email_send_id"])

    op.create_table(
        "suppressions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("email_blind_index", sa.LargeBinary(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_suppressions_tenant_id", "suppressions", ["tenant_id"])
    op.create_index(
        "uq_suppressions_tenant_email",
        "suppressions",
        ["tenant_id", "email_blind_index"],
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

    # activities/email_events: append-only, same two-layer enforcement
    # (revoked grant + raising trigger) as consent_records (0007) —
    # reusing the refuse_mutation() function 0001 already installed.
    for table in APPEND_ONLY:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION refuse_mutation();
            """
        )

    for table in TENANT_SCOPED:
        if table in APPEND_ONLY:
            op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        else:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")

    for code, description in NEW_PERMISSIONS:
        bind.execute(
            sa.text("INSERT INTO permissions (code, description) VALUES (:c, :d)"),
            {"c": code, "d": description},
        )
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_code, permission_code) VALUES "
            "('admin', 'deal:manage'), ('admin', 'campaign:manage'), "
            "('super_admin', 'deal:manage'), ('super_admin', 'campaign:manage')"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_code IN "
            "('deal:manage', 'campaign:manage')"
        )
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code IN ('deal:manage', 'campaign:manage')")
    )

    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_table("suppressions")
    op.drop_table("email_events")
    op.drop_table("email_sends")
    op.drop_table("campaigns")
    op.drop_table("email_templates")
    op.drop_table("segments")
    op.drop_table("activities")
    op.drop_table("notes")
    op.drop_table("tasks")
    op.drop_table("deals")

    for enum_name in ("email_send_status", "campaign_status", "deal_stage"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
