"""Sprint 5: tenant themes (02 §4.3).

Theming *features* are Phase 5; the table and its read path exist now so the
middleware contract does not change later, and so the Phase 1 demo target —
two hostnames rendering differently — is real rather than mocked. The two
demo tenants are seeded with visibly different palettes.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"

THEME_SEED = {
    "demo": {
        "primary_color": "#1B2A4A",
        "secondary_color": "#C9A227",
        "support_email": "support@ttli.local",
    },
    "acme": {
        "primary_color": "#14532D",
        "secondary_color": "#F59E0B",
        "support_email": "support@meridian.local",
    },
}


def _uuid7() -> uuid.UUID:
    ms = int(time.time() * 1000)
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6:16] = os.urandom(10)
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(b))


def upgrade() -> None:
    op.create_table(
        "tenant_themes",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("primary_color", sa.String(7), nullable=True),
        sa.Column("secondary_color", sa.String(7), nullable=True),
        sa.Column("login_background_url", sa.Text(), nullable=True),
        sa.Column("support_email", pg.CITEXT(), nullable=True),
        sa.Column("email_footer_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.execute("ALTER TABLE tenant_themes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_themes FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_themes
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_themes TO {APP_ROLE}")

    conn = op.get_bind()
    for slug, theme in THEME_SEED.items():
        tenant_id = conn.execute(
            sa.text("SELECT id FROM tenants WHERE slug = :s"), {"s": slug}
        ).scalar()
        if tenant_id is None:  # production seeds no demo tenants (0002)
            continue
        # RLS is FORCEd, so even the migration owner must declare the tenant.
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            sa.text(
                "INSERT INTO tenant_themes "
                "(id, tenant_id, primary_color, secondary_color, support_email) "
                "VALUES (:i, :t, :p, :s, :e)"
            ),
            {
                "i": _uuid7(),
                "t": tenant_id,
                "p": theme["primary_color"],
                "s": theme["secondary_color"],
                "e": theme["support_email"],
            },
        )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_themes")
    op.drop_table("tenant_themes")
