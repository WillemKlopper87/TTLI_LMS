"""Pure-function tests for the completion rule engine (`services/completion.py`,
02 §5.2, REQ-BYPASS-01/02) — no Postgres, no Redis, no fixtures beyond plain
Python values. `evaluate`/`merge_rules` are already 100% pure (no DB import
anywhere in the module); until now they were only exercised indirectly
through `test_assessment.py`'s integration suite (TTLI_Audit_Report_2026-09-02.md
M5's exact example of already-pure code with zero direct test coverage).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from src.services.completion import CompletionRules, evaluate, merge_rules

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def test_merge_rules_lesson_overrides_per_field_not_wholesale():
    course = {"minimum_time_seconds": 60, "quiz_pass_score": 70}
    lesson = {"quiz_pass_score": 90}
    merged = merge_rules(course, lesson)
    # The lesson only set quiz_pass_score -- minimum_time_seconds must
    # still come from the course, not be dropped.
    assert merged.minimum_time_seconds == 60
    assert merged.quiz_pass_score == 90


def test_merge_rules_lesson_none_values_do_not_clear_course_fields():
    course = {"minimum_time_seconds": 60}
    lesson = {"minimum_time_seconds": None, "quiz_pass_score": 80}
    merged = merge_rules(course, lesson)
    assert merged.minimum_time_seconds == 60
    assert merged.quiz_pass_score == 80


def test_evaluate_with_no_rules_set_is_trivially_met():
    rules = CompletionRules()
    result = evaluate(rules, first_seen_at=NOW, now=NOW)
    assert result.met is True
    assert result.checks == ()


def test_minimum_time_seconds_not_yet_met():
    rules = CompletionRules(minimum_time_seconds=120)
    result = evaluate(rules, first_seen_at=NOW, now=NOW + timedelta(seconds=30))
    assert result.met is False
    check = result.checks[0]
    assert check.rule == "minimum_time_seconds"
    assert check.met is False
    assert "30s spent of 120s required" in check.reason


def test_minimum_time_seconds_met():
    rules = CompletionRules(minimum_time_seconds=120)
    result = evaluate(rules, first_seen_at=NOW, now=NOW + timedelta(seconds=180))
    assert result.met is True
    assert result.checks[0].met is True


def test_video_watch_percentage_none_is_treated_as_zero_not_inapplicable():
    rules = CompletionRules(video_watch_percentage=80)
    result = evaluate(rules, first_seen_at=NOW, now=NOW, video_watched_percentage=None)
    assert result.met is False
    assert "0% watched of 80% required" in result.checks[0].reason


def test_video_watch_percentage_met():
    rules = CompletionRules(video_watch_percentage=80)
    result = evaluate(rules, first_seen_at=NOW, now=NOW, video_watched_percentage=85.0)
    assert result.met is True


@pytest.mark.parametrize(
    ("quiz_passed", "expected_met", "expected_reason_fragment"),
    [
        (True, True, "Quiz passed."),
        (False, False, "not yet passed"),
        (None, False, "Awaiting manual grading"),
    ],
)
def test_quiz_pass_score_distinguishes_failed_from_ungraded(
    quiz_passed, expected_met, expected_reason_fragment
):
    rules = CompletionRules(quiz_pass_score=70)
    result = evaluate(rules, first_seen_at=NOW, now=NOW, quiz_passed=quiz_passed)
    check = result.checks[0]
    assert check.met is expected_met
    assert expected_reason_fragment in check.reason


def test_survey_required_false_adds_no_check():
    rules = CompletionRules(survey_required=False)
    result = evaluate(rules, first_seen_at=NOW, now=NOW)
    assert result.checks == ()
    assert result.met is True


def test_survey_required_true_and_not_responded():
    rules = CompletionRules(survey_required=True)
    result = evaluate(rules, first_seen_at=NOW, now=NOW, survey_responded=False)
    assert result.met is False
    assert result.checks[0].rule == "survey_required"


def test_assignment_approval_required_met():
    rules = CompletionRules(assignment_approval_required=True)
    result = evaluate(rules, first_seen_at=NOW, now=NOW, assignment_approved=True)
    assert result.met is True


def test_live_attendance_required_always_fails_no_subsystem_yet():
    """An authored rule for a subsystem that doesn't exist must fail
    explicitly, never be silently ignored (the module's own docstring)."""
    rules = CompletionRules(live_attendance_required=True)
    result = evaluate(rules, first_seen_at=NOW, now=NOW)
    assert result.met is False
    check = result.checks[0]
    assert check.rule == "live_attendance_required"
    assert check.met is False
    assert "Phase 5" in check.reason


def test_multiple_rules_all_must_pass():
    rules = CompletionRules(minimum_time_seconds=60, quiz_pass_score=70)
    result = evaluate(
        rules,
        first_seen_at=NOW,
        now=NOW + timedelta(seconds=120),
        quiz_passed=False,
    )
    assert result.met is False
    assert len(result.checks) == 2
    assert result.checks[0].met is True  # time
    assert result.checks[1].met is False  # quiz


def test_as_json_snapshot_shape():
    rules = CompletionRules(quiz_pass_score=70)
    result = evaluate(rules, first_seen_at=NOW, now=NOW, quiz_passed=True)
    snapshot = result.as_json()
    assert snapshot == {
        "met": True,
        "checks": [{"rule": "quiz_pass_score", "met": True, "reason": "Quiz passed."}],
    }
