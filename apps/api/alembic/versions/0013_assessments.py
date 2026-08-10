"""Phase 4 sprint 3: quizzes, surveys and assignments (02 §7.5/7.6/7.7,
REQ-ASSESS-01…06, REQ-BYPASS-05/06/07/08).

`quizzes`/`quiz_questions`/`surveys`/`survey_questions`/`assignments` are
global, not tenant-scoped — same reasoning as `courses`/`video_assets`
(0011/0012): they belong to a lesson, which belongs to a globally-shared
course. `quiz_attempts`/`quiz_answers`/`survey_responses`/
`assignment_submissions` are tenant-scoped/RLS, like `enrolments` and
`video_progress` — they belong to one tenant's learner activity.

**Anonymous surveys** (REQ-ASSESS-05) reuse the exact blind-index
mechanism `contacts.email_blind_index` already established (`core/crypto.py`,
`CryptoBox.blind_index`) rather than inventing a second one: for an
anonymous response, `respondent_reference` is the blind index of
`f"{survey_id}:{enrolment_id}"` — a stable pseudonym that lets the system
detect a duplicate submission from the same enrolment, and lets the
completion rule engine confirm *that this enrolment specifically*
answered a required survey, without ever storing `enrolment_id` (or
anything that identifies who) on the row itself. `user_id` is genuinely
absent for anonymous responses, not nullable-and-null — the CHECK
constraint below encodes exactly one of `user_id`/`respondent_reference`
is set, mirroring `consent_records`' existing `ck_..._one_subject` pattern
(0007).

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "app_user"
TENANT_SCOPED = ("quiz_attempts", "quiz_answers", "survey_responses", "assignment_submissions")
SURVEY_RESPONSE_MODE_VALUES = ("identified", "anonymous")


def upgrade() -> None:
    survey_response_mode = pg.ENUM(
        *SURVEY_RESPONSE_MODE_VALUES, name="survey_response_mode", create_type=False
    )
    survey_response_mode.create(op.get_bind())

    # --- Quizzes ---
    op.create_table(
        "quizzes",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "randomise_questions", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "randomise_options", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("pass_score", sa.Integer(), nullable=False, server_default=sa.text("70")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "quiz_questions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "quiz_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("quizzes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # REQ-ASSESS-01 names ten types; this sprint's cut is the four that
        # can be auto-graded plus long/short text for manual grading
        # (REQ-ASSESS-03) — file upload/ranking/matching/NPS/Likert are a
        # documented gap, not an oversight.
        sa.Column("question_type", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        # [{"id": "...", "text": "...", "correct": bool}, ...] for choice
        # types; empty for short/long text.
        sa.Column("options", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_quiz_questions_quiz_id", "quiz_questions", ["quiz_id"])

    op.create_table(
        "quiz_attempts",
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
            "quiz_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("quizzes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        # The randomised question/option order actually shown this
        # attempt — persisted so re-grading or a support dispute sees
        # exactly what the learner saw, not today's shuffle.
        sa.Column(
            "question_order", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_quiz_attempts_tenant_id", "quiz_attempts", ["tenant_id"])
    op.create_index("ix_quiz_attempts_enrolment_quiz", "quiz_attempts", ["enrolment_id", "quiz_id"])

    op.create_table(
        "quiz_answers",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("quiz_attempts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("quiz_questions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Correct answers are never sent to the client before submission
        # (03 §6.5) — selected_option_ids/text_answer is what the learner
        # actually chose, is_correct/points_awarded is what the server
        # decided, computed after the fact, never trusted from the client.
        sa.Column("selected_option_ids", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("text_answer", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("points_awarded", sa.Numeric(5, 2), nullable=True),
    )
    op.create_index("ix_quiz_answers_tenant_id", "quiz_answers", ["tenant_id"])
    op.create_index("ix_quiz_answers_attempt_id", "quiz_answers", ["attempt_id"])

    # --- Surveys ---
    op.create_table(
        "surveys",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("response_mode", survey_response_mode, nullable=False),
        sa.Column("minimum_group_size", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "survey_questions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "survey_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("surveys.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_type", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_index("ix_survey_questions_survey_id", "survey_questions", ["survey_id"])

    op.create_table(
        "survey_responses",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "survey_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("surveys.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Exactly one of these two is set (CHECK below) — identified
        # responses carry user_id; anonymous responses carry a blind-index
        # respondent_reference instead and never touch user_id at all.
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("respondent_reference", sa.LargeBinary(), nullable=True),
        sa.Column("answers", pg.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_survey_responses_tenant_id", "survey_responses", ["tenant_id"])
    op.create_index(
        "uq_survey_responses_survey_reference",
        "survey_responses",
        ["survey_id", "respondent_reference"],
        unique=True,
    )
    op.create_index(
        "uq_survey_responses_survey_user", "survey_responses", ["survey_id", "user_id"], unique=True
    )
    op.execute(
        """
        ALTER TABLE survey_responses ADD CONSTRAINT ck_survey_responses_one_subject
        CHECK ((user_id IS NULL) <> (respondent_reference IS NULL))
        """
    )

    # --- Assignments ---
    op.create_table(
        "assignments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("max_score", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column(
            "approval_required", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "assignment_submissions",
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
            "assignment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assignments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("object_key", sa.Text(), nullable=False),
        # Virus-scanned before the file is readable by anyone
        # (REQ-BYPASS-08) — same fail-closed rule as the payment-proof and
        # video-source uploads; scanned_at/scan_result record that it
        # happened, not just that storage accepted the bytes.
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_result", sa.String(16), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "reviewed_by_user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_assignment_submissions_tenant_id", "assignment_submissions", ["tenant_id"])
    op.create_index(
        "ix_assignment_submissions_enrolment_assignment",
        "assignment_submissions",
        ["enrolment_id", "assignment_id"],
    )

    # --- lessons gains three more optional links, same pattern as
    # video_asset_id (0012) ---
    op.add_column(
        "lessons",
        sa.Column(
            "quiz_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("quizzes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "lessons",
        sa.Column(
            "survey_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("surveys.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "lessons",
        sa.Column(
            "assignment_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("assignments.id", ondelete="SET NULL"),
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

    # Global tables — same reasoning as video_assets/transcode_jobs (0012):
    # the narrow authoring endpoints in this sprint write to them, so
    # app_user needs the full grant, not the read-only treatment 0011 gave
    # courses/modules/lessons before either had a writer.
    for table in ("quizzes", "quiz_questions", "surveys", "survey_questions", "assignments"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")
    # lessons.quiz_id/survey_id/assignment_id are set by this sprint's
    # attach endpoints, same UPDATE grant 0012 already put in place for
    # video_asset_id — no new grant needed here.


def downgrade() -> None:
    for table in TENANT_SCOPED:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_column("lessons", "assignment_id")
    op.drop_column("lessons", "survey_id")
    op.drop_column("lessons", "quiz_id")
    op.drop_table("assignment_submissions")
    op.drop_table("assignments")
    op.drop_table("survey_responses")
    op.drop_table("survey_questions")
    op.drop_table("surveys")
    op.drop_table("quiz_answers")
    op.drop_table("quiz_attempts")
    op.drop_table("quiz_questions")
    op.drop_table("quizzes")
    op.execute("DROP TYPE IF EXISTS survey_response_mode")
