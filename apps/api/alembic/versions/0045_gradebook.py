"""Marks for assignments, and a weight per assessable item (BACKLOG P18).

Revision ID: 0045
Revises: 0044

The unified achievement model is deliberately *additive*: nothing here
changes what completes a lesson or issues a certificate. `completion_rules`
remains the gate exactly as before (02 §5.2), and this adds the reporting
layer that never existed alongside it.

Two gaps close.

`assignments.max_score` has shipped since 0013 declaring an assignment is
"out of 100", while `assignment_submissions` had nowhere to record a mark
against it -- the review flow is approve/reject only. An administrator
could set max_score to 50 and change nothing, which made the field a
promise the schema could not keep. `score` gives it one.

`weight` gives the gradebook something to weigh with. Both default to 1,
so every existing quiz and assignment counts equally until someone says
otherwise and no historical grade shifts under an unchanged course.

Deliberately NOT added: moderation columns. A `moderated_by`/`moderated_at`
pair with no moderation workflow behind it would be exactly the dangling
field this migration exists to fix -- the same mistake as `max_score`, and
as `enrolments.cohort_id` before P17 settled it. They arrive with the
workflow that writes them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable and unbacked by a default on purpose: a submission that has
    # been approved but not marked is a real, ordinary state (approval and
    # marking are separate acts), and NULL says "not marked" where 0 would
    # say "marked, scored zero". The gradebook reports those differently.
    op.add_column(
        "assignment_submissions",
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=True),
    )
    # The upper bound is per-assignment (`assignments.max_score`) and so
    # cannot live in a single-table CHECK; services/gradebook.py enforces
    # it on write. This constraint catches what it can from here.
    op.create_check_constraint(
        "ck_assignment_submissions_score_non_negative",
        "assignment_submissions",
        "score IS NULL OR score >= 0",
    )

    for table in ("quizzes", "assignments"):
        op.add_column(
            table,
            sa.Column(
                "weight",
                sa.Numeric(precision=6, scale=2),
                server_default=sa.text("1"),
                nullable=False,
            ),
        )
        # A zero-weight item would sit in the gradebook contributing
        # nothing while still looking gradeable; excluding an item is what
        # "don't add it to the course" is for.
        op.create_check_constraint(
            f"ck_{table}_weight_positive",
            table,
            "weight > 0",
        )


def downgrade() -> None:
    for table in ("quizzes", "assignments"):
        op.drop_constraint(f"ck_{table}_weight_positive", table, type_="check")
        op.drop_column(table, "weight")

    op.drop_constraint(
        "ck_assignment_submissions_score_non_negative",
        "assignment_submissions",
        type_="check",
    )
    op.drop_column("assignment_submissions", "score")
