"""Phase 2 close-out: a `message` column on `leads` for the contact form.

The real ttli.co.za site has a "Get In Touch" contact page with no working
form, just contact details (docs/brand/ttli-brand-identity.md). Building a
real one is a genuine improvement, not fabricated content — it reuses
`POST /leads` end to end (consent, rate limiting, admin visibility) rather
than a parallel table, so a contact-form submission just is a lead with a
message attached.

`message` follows the same progressive-profiling overwrite semantics as
`training_goal` et al. (services/leads.py) — a known, accepted tradeoff for
a single contact submitting more than once: the newer message replaces the
older one rather than both being kept, which is fine for a low-volume
marketing form and not worth a separate messages table.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "message")
