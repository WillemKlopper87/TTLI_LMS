"""Learning-integrity backstops: watch-time tracking, attempt/version
uniqueness (H-6, H-7).

fable5.1_review.md H-6/H-7:

- `services/video_progress.py::record_heartbeat` now takes
  `SELECT ... FOR UPDATE` on the `VideoProgress` row and bounds the
  watched-seconds a single heartbeat may add by how far the reported
  position has genuinely moved since the row's last heartbeat, at that
  heartbeat's own playback_rate — closing both the "N parallel
  heartbeats each add the full interval" race and the "call heartbeat
  repeatedly without playback ever advancing" variant. `last_position_
  seconds` is the column that comparison needs; `furthest_position_
  seconds` can't serve it (it only ever grows, so it can't tell "played
  forward since last time" apart from "replayed an earlier section").

- `services/quiz.py::start_attempt`/`submit_attempt` and
  `services/assignment.py::submit` now lock the parent `Enrolment` row
  (`SELECT ... FOR UPDATE`) before counting existing attempts / the
  latest version and inserting the next one — the same "lock the parent
  to serialise the child insert" idiom `services/workshops/booking.py`
  already uses. The three unique indexes below are the database-level
  backstop behind those locks, exactly as 0043 added for H-2/H-3: even a
  creation path that reaches the database some other way cannot leave
  two attempts sharing an attempt_number, two answers on one question of
  one attempt, or two submissions sharing a version.

Each attempt/answer/submission index replaces a same-column-prefix plain
index already present (`ix_quiz_attempts_enrolment_quiz`, `ix_quiz_
answers_attempt_id`, `ix_assignment_submissions_enrolment_assignment`)
rather than adding alongside it — a unique index on the superset already
serves every query the plain one would.

Checked against this dev database before writing this migration: zero
existing duplicates on any of the three new unique keys (see this
workstream's own report for the query run).

Revision ID: 0044
Revises: 0043
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "video_progress", sa.Column("last_position_seconds", sa.Numeric(10, 2), nullable=True)
    )

    op.drop_index("ix_quiz_attempts_enrolment_quiz", table_name="quiz_attempts")
    op.create_index(
        "uq_quiz_attempts_enrolment_quiz_attempt_number",
        "quiz_attempts",
        ["enrolment_id", "quiz_id", "attempt_number"],
        unique=True,
    )

    op.drop_index("ix_quiz_answers_attempt_id", table_name="quiz_answers")
    op.create_index(
        "uq_quiz_answers_attempt_question",
        "quiz_answers",
        ["attempt_id", "question_id"],
        unique=True,
    )

    op.drop_index(
        "ix_assignment_submissions_enrolment_assignment", table_name="assignment_submissions"
    )
    op.create_index(
        "uq_assignment_submissions_enrolment_assignment_version",
        "assignment_submissions",
        ["enrolment_id", "assignment_id", "version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_assignment_submissions_enrolment_assignment_version",
        table_name="assignment_submissions",
    )
    op.create_index(
        "ix_assignment_submissions_enrolment_assignment",
        "assignment_submissions",
        ["enrolment_id", "assignment_id"],
    )

    op.drop_index("uq_quiz_answers_attempt_question", table_name="quiz_answers")
    op.create_index("ix_quiz_answers_attempt_id", "quiz_answers", ["attempt_id"])

    op.drop_index("uq_quiz_attempts_enrolment_quiz_attempt_number", table_name="quiz_attempts")
    op.create_index("ix_quiz_attempts_enrolment_quiz", "quiz_attempts", ["enrolment_id", "quiz_id"])

    op.drop_column("video_progress", "last_position_seconds")
