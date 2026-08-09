"""Replace the `demo` tenant's placeholder identity with TTLI's real brand.

0002 seeded the `demo` tenant as "TTLI Executive Institute" and 0006 gave it
a placeholder navy/gold theme — both invented, because at the time nobody
had looked at the actual customer. `docs/brand/ttli-brand-identity.md`
records what was extracted from https://ttli.co.za/ and why; this migration
is that extraction applied to the seed data it was always meant to replace.

`acme` is untouched on purpose — it exists to prove per-tenant theming
works, and giving it TTLI's own brand would defeat that.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_NAME = "TTLI Executive Institute"
_NEW_NAME = "Themba Thandeka Leadership Institute"

_OLD = {"primary_color": "#1B2A4A", "secondary_color": "#C9A227", "logo_url": None}
_NEW = {
    "primary_color": "#8E151C",
    "secondary_color": "#BC222A",
    "logo_url": "/brand/ttli-logo.png",
}


def _apply(name: str, theme: dict[str, str | None]) -> None:
    conn = op.get_bind()
    tenant_id = conn.execute(sa.text("SELECT id FROM tenants WHERE slug = 'demo'")).scalar()
    if tenant_id is None:  # production seeds no demo tenants (0002)
        return
    conn.execute(sa.text("UPDATE tenants SET name = :n WHERE id = :t"), {"n": name, "t": tenant_id})
    # RLS is FORCEd on tenant_themes, so even the migration owner must declare the tenant.
    conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
    conn.execute(
        sa.text(
            "UPDATE tenant_themes SET primary_color = :p, secondary_color = :s, logo_url = :l "
            "WHERE tenant_id = :t"
        ),
        {"p": theme["primary_color"], "s": theme["secondary_color"], "l": theme["logo_url"], "t": tenant_id},
    )


def upgrade() -> None:
    _apply(_NEW_NAME, _NEW)


def downgrade() -> None:
    _apply(_OLD_NAME, _OLD)
