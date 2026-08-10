"""Phase 4 sprint 4: certificates and badges (02 §8, 03 §7,
REQ-CRED-01…08) — the final Phase 4 sprint.

`certificate_templates`/`badge_templates` are global, matching every other
question/content-bank table this phase added (`quizzes`, `video_assets`);
`certificates`/`badges`/`credential_verifications` are tenant-scoped/RLS,
matching `enrolments`.

**`verification_token` is never stored in plaintext, but it must be
reconstructable** — unlike a magic link or refresh token, which are used
once and never needed again, this one is embedded in a PDF's QR code at
issuance *and* has to be rebuildable later for `GET /badges/{id}/share/
linkedin`'s `certUrl` field. A one-way hash (`core/security.py`'s
`new_token()`/`hash_token()`, used for magic links/refresh tokens)
cannot support that — caught before this migration was ever committed,
not after. So this reuses `contacts.email_encrypted`/`email_blind_index`'s
pattern instead: `verification_token_encrypted` (`CryptoBox.encrypt`,
reversible) holds the value the share endpoint decrypts back out;
`verification_token_blind_index` (`CryptoBox.blind_index`, deterministic)
is what `GET /verify/{token}` looks up by, in O(1), without ever needing
to decrypt every row to find a match. `certificate_number` is a separate,
unencrypted field — a public, opaque-but-not-secret serial printed on the
certificate (02 §8.1 says "unguessable, not sequential", not "secret"),
the same distinction `invoices.number` (sequential, public) already draws
against something that actually needs to stay confidential.

`courses` gains `certificate_template_id`/`badge_template_id` — 02 §5.1
described these as already present on `courses`, but `0011` deliberately
deferred them: a FK to a table that doesn't exist yet isn't buildable, and
building the target of the FK is exactly this sprint's job.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = ("certificates", "badges", "credential_verifications")
CREDENTIAL_STATUS_VALUES = ("valid", "expired", "revoked")


def upgrade() -> None:
    credential_status = pg.ENUM(
        *CREDENTIAL_STATUS_VALUES, name="credential_status", create_type=False
    )
    credential_status.create(op.get_bind())

    op.create_table(
        "certificate_templates",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        # The issuing organisation (e.g. "Themba Thandeka Leadership
        # Institute") — distinct from signatory_name, the *person* whose
        # name appears on the "Signed:" line. badge_templates already
        # separates these two concepts (its own issuer_name column); this
        # mirrors that rather than reusing signatory_name for both, which
        # would put a person's name in LinkedIn's organizationName field.
        sa.Column("issuer_name", sa.Text(), nullable=False),
        sa.Column("signatory_name", sa.Text(), nullable=False),
        sa.Column("signatory_title", sa.Text(), nullable=False),
        # REQ-CRED-08 — optional, pending 01 §1.4 #7 (accreditation body).
        sa.Column("cpd_points", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "certificates",
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
            "certificate_template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("certificate_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("certificate_number", sa.Text(), nullable=False),
        # Encrypted + blind-indexed, not one-way hashed — the exact
        # contacts.email_encrypted/email_blind_index pattern (0007), and
        # for the same reason: `GET /verify/{token}` needs O(1) lookup by
        # value (the blind index), but the LinkedIn share endpoint also
        # needs to *reconstruct* the original URL later, which a one-way
        # hash can never support — that gap was caught before this
        # migration was ever committed, not after.
        sa.Column("verification_token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("verification_token_blind_index", sa.LargeBinary(), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", credential_status, nullable=False, server_default="valid"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column(
            "revoked_by_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("pdf_object_key", sa.Text(), nullable=True),
        # REQ-CRED-07 — learner-controlled, defaults to the most private
        # option rather than opting a learner into public exposure.
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
        # Learner name, course title, issuer as they were at issue (02
        # §8.1) — a later name change must not invalidate a certificate
        # already in circulation.
        sa.Column("snapshot", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
    )
    op.create_index("ix_certificates_tenant_id", "certificates", ["tenant_id"])
    op.create_index("uq_certificates_enrolment", "certificates", ["enrolment_id"], unique=True)
    op.create_index("uq_certificates_number", "certificates", ["certificate_number"], unique=True)
    op.create_index(
        "uq_certificates_token_blind_index",
        "certificates",
        ["verification_token_blind_index"],
        unique=True,
    )

    op.create_table(
        "badge_templates",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("criteria", sa.Text(), nullable=False),
        sa.Column("issuer_name", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "badges",
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
            "badge_template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("badge_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "certificate_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("certificates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_badges_tenant_id", "badges", ["tenant_id"])
    op.create_index("uq_badges_enrolment", "badges", ["enrolment_id"], unique=True)

    op.create_table(
        "credential_verifications",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Nullable — a lookup for an unknown/invalid token is still logged
        # for abuse detection (02 §8.3) even though it matches no row.
        sa.Column(
            "certificate_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("certificates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Same blind index certificates.verification_token_blind_index
        # uses — the same raw token always produces the same value here,
        # so a log entry and the certificate it matched can be correlated
        # without decrypting anything.
        sa.Column("token_blind_index", sa.LargeBinary(), nullable=False),
        sa.Column("ip", pg.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_credential_verifications_tenant_id", "credential_verifications", ["tenant_id"]
    )
    op.create_index(
        "ix_credential_verifications_certificate_id", "credential_verifications", ["certificate_id"]
    )

    op.add_column(
        "courses",
        sa.Column(
            "certificate_template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("certificate_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "courses",
        sa.Column(
            "badge_template_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("badge_templates.id", ondelete="SET NULL"),
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

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON certificate_templates TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON badge_templates TO {APP_ROLE}")
    # courses' first writable columns since 0011 left it read-only —
    # same UPDATE-only precedent 0012 set for lessons.
    op.execute(f"GRANT UPDATE ON courses TO {APP_ROLE}")


def downgrade() -> None:
    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_column("courses", "badge_template_id")
    op.drop_column("courses", "certificate_template_id")
    op.drop_table("credential_verifications")
    op.drop_table("badges")
    op.drop_table("badge_templates")
    op.drop_table("certificates")
    op.drop_table("certificate_templates")
    op.execute("DROP TYPE IF EXISTS credential_status")
