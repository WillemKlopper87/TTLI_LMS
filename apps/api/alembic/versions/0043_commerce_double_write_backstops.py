"""Unique backstops against double fulfilment / double refund (H-2, H-3).

fable5.1_review.md H-2/H-3: `services/orders.py::_fulfil_order` and
`services/refunds.py::process_refund` now serialise concurrent callers
with `SELECT ... FOR UPDATE` on the `Order` row, mirroring
`services/workshops/booking.py`'s locking idiom -- that is the actual
guard. These three unique indexes are the database-level backstop behind
it: even a fulfilment/refund path that reaches the database some other
way (a future caller that forgets to lock, a manual script) cannot leave
two invoices on one order, two credit notes on one invoice, or two
refunds on one order -- the second write fails loudly at the constraint
instead of silently doubling the accounting.

Each replaces a same-column plain index already present (`ix_invoices_
order_id`, `ix_credit_notes_invoice_id`, `ix_refunds_order_id`) rather
than adding alongside it -- a unique index already serves every query a
plain one would, so keeping both would just be redundant metadata drift
between the models and the schema.

Checked against this dev database before writing this migration: zero
existing duplicates on any of the three columns, so this is a clean add,
not a cleanup -- see the workstream's own report for the query run.

Revision ID: 0043
Revises: 0042
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_invoices_order_id", table_name="invoices")
    op.create_index("uq_invoices_order_id", "invoices", ["order_id"], unique=True)

    op.drop_index("ix_credit_notes_invoice_id", table_name="credit_notes")
    op.create_index("uq_credit_notes_invoice_id", "credit_notes", ["invoice_id"], unique=True)

    op.drop_index("ix_refunds_order_id", table_name="refunds")
    op.create_index("uq_refunds_order_id", "refunds", ["order_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_refunds_order_id", table_name="refunds")
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])

    op.drop_index("uq_credit_notes_invoice_id", table_name="credit_notes")
    op.create_index("ix_credit_notes_invoice_id", "credit_notes", ["invoice_id"])

    op.drop_index("uq_invoices_order_id", table_name="invoices")
    op.create_index("ix_invoices_order_id", "invoices", ["order_id"])
