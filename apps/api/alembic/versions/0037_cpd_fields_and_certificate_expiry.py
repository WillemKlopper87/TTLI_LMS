"""CPD fields beyond one integer, and certificate expiry (`docs/BACKLOG.md`
P13; `docs/research/feature-matrix-coverage.md` audit #18).

`certificate_templates.cpd_points` has existed since `0014` as a bare
integer — the accreditation body's own reference number and the validity
period a real CPD certification carries were never modelled, and
`Certificate.expires_at` (present since `0014` too) has never once been
set by any issuance code path, since nothing computed a validity date to
put there.

Three columns, all nullable and all opt-in: an untouched template (no
`cpd_validity_months`) issues a certificate with `expires_at IS NULL`,
identical to today's behaviour — this is additive, not a retrofit of
existing accreditation-less courses.

Revision ID: 0037
Revises: 0036
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("certificate_templates", sa.Column("cpd_body", sa.Text(), nullable=True))
    op.add_column("certificate_templates", sa.Column("cpd_reference", sa.Text(), nullable=True))
    op.add_column(
        "certificate_templates", sa.Column("cpd_validity_months", sa.Integer(), nullable=True)
    )
    op.create_check_constraint(
        "ck_certificate_templates_cpd_validity_positive",
        "certificate_templates",
        "cpd_validity_months IS NULL OR cpd_validity_months > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_certificate_templates_cpd_validity_positive",
        "certificate_templates",
        type_="check",
    )
    op.drop_column("certificate_templates", "cpd_validity_months")
    op.drop_column("certificate_templates", "cpd_reference")
    op.drop_column("certificate_templates", "cpd_body")
