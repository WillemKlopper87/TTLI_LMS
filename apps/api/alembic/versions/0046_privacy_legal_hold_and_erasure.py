"""Legal hold and erasure tombstone bookkeeping on users (BACKLOG T12).

Revision ID: 0046
Revises: 0045

04_SECURITY_AND_COMPLIANCE.md §5.3 specifies POPIA's data-subject rights as
implemented; two of the five (Access/Portability as a JSON export, Deletion
as anonymisation-not-deletion) had nowhere to record their own bookkeeping,
and legal hold was flagged there as entirely unspecified ("No mechanism is
specified for suspending deletion during a dispute. Needed before the first
enterprise contract."). Nothing here is a new table: `users` already
survives erasure by design (the row is never deleted, only its identity
columns are tombstoned), so this is additive columns on the row that
already exists, not a new privilege boundary — no new GRANT is needed
(0001's per-table GRANT already covers every column on `users`, present
and future).

Deliberately no new `users.status` value for "erased": `services.
tenant_users.set_status` already validates status is 'active' or
'suspended' and terminates every live session on that transition
(fable5.1_review.md H-11's fix) — erasure reuses that exact mechanism
(status -> 'suspended') rather than inventing a third status the rest of
the codebase (login checks, admin listings) would need to learn about
for one narrow event. `erased_at` is the actual erasure marker and the
idempotency guard (services/privacy.py refuses a second erasure once set).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("users", sa.Column("legal_hold_reason", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("legal_hold_set_at", sa.DateTime(timezone=True), nullable=True),
    )
    # SET NULL, not RESTRICT: the admin who placed a hold may themselves
    # later be erased or leave the tenant — the hold itself must outlive
    # them, same reasoning as certificates.revoked_by_user_id.
    op.add_column(
        "users",
        sa.Column(
            "legal_hold_set_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("users", sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "erased_at")
    op.drop_column("users", "legal_hold_set_by")
    op.drop_column("users", "legal_hold_set_at")
    op.drop_column("users", "legal_hold_reason")
    op.drop_column("users", "legal_hold")
