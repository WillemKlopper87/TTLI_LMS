"""The server-side completion rule engine (02 §5.2, REQ-BYPASS-01/02).

The frontend may display progress; this module is the only thing that
decides whether a lesson is actually complete — no client assertion is
ever trusted, and every timestamp used here is server-assigned.

A rule field whose subsystem doesn't exist yet — quiz, survey, assignment,
live attendance (Phase 4 sprint 3, Phase 5) — evaluates as **not met**,
with a specific reason, rather than being silently ignored. An absent
subsystem is not the same as an absent rule: a lesson authored with
`quiz_pass_score` set must not complete just because no quiz engine exists
to check it against. `video_watch_percentage` graduated out of this list
in Phase 4 sprint 2 — real watch data now backs it
(services/video_progress.py), so it's evaluated for real below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel


class CompletionRules(BaseModel):
    """02 §5.2's jsonb shape. Every field optional — an absent field means
    the rule does not apply."""

    minimum_time_seconds: int | None = None
    video_watch_percentage: int | None = None
    quiz_pass_score: int | None = None
    quiz_max_attempts: int | None = None
    survey_required: bool | None = None
    assignment_approval_required: bool | None = None
    live_attendance_required: bool | None = None
    minimum_interval_seconds: int | None = None


def merge_rules(course_rules: dict[str, Any], lesson_rules: dict[str, Any]) -> CompletionRules:
    """The lesson's own completion_rules overrides the course default
    per-field, never wholesale (02 §5.2) — a lesson rule set with only
    `quiz_pass_score` present still inherits the course's
    `minimum_time_seconds` rather than dropping it."""
    merged = dict(course_rules)
    merged.update({k: v for k, v in lesson_rules.items() if v is not None})
    return CompletionRules.model_validate(merged)


@dataclass(frozen=True, slots=True)
class RuleCheck:
    rule: str
    met: bool
    reason: str


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    met: bool
    checks: tuple[RuleCheck, ...]

    def as_json(self) -> dict[str, Any]:
        """The snapshot stored in lesson_completions.rule_evaluation (02
        §7.2) — what makes a completion dispute resolvable later."""
        return {
            "met": self.met,
            "checks": [{"rule": c.rule, "met": c.met, "reason": c.reason} for c in self.checks],
        }


# Rule fields whose subsystem does not exist yet. Presence (a truthy value)
# always fails the check, with a reason naming what's missing — never a
# silent pass.
_NOT_YET_AVAILABLE = {
    "quiz_pass_score": "Quizzes are not available yet (Phase 4 sprint 3).",
    "survey_required": "Surveys are not available yet (Phase 4 sprint 3).",
    "assignment_approval_required": "Assignments are not available yet (Phase 4 sprint 3).",
    "live_attendance_required": "Workshop attendance tracking is not available yet (Phase 5).",
}


def evaluate(
    rules: CompletionRules,
    *,
    first_seen_at: datetime,
    now: datetime | None = None,
    video_watched_percentage: float | None = None,
) -> RuleEvaluation:
    now = now or datetime.now(UTC)
    checks: list[RuleCheck] = []

    if rules.minimum_time_seconds is not None:
        elapsed = (now - first_seen_at).total_seconds()
        met = elapsed >= rules.minimum_time_seconds
        checks.append(
            RuleCheck(
                rule="minimum_time_seconds",
                met=met,
                reason=(
                    "Minimum time met."
                    if met
                    else f"{int(elapsed)}s spent of {rules.minimum_time_seconds}s required."
                ),
            )
        )

    if rules.video_watch_percentage is not None:
        # None means no validated heartbeat data exists yet for this
        # enrolment/lesson (services/video_progress.py::watch_percentage)
        # — treated as 0%, never as "the rule doesn't apply".
        watched = video_watched_percentage or 0.0
        met = watched >= rules.video_watch_percentage
        checks.append(
            RuleCheck(
                rule="video_watch_percentage",
                met=met,
                reason=(
                    "Video watch requirement met."
                    if met
                    else f"{watched:.0f}% watched of {rules.video_watch_percentage}% required."
                ),
            )
        )

    for field_name, reason in _NOT_YET_AVAILABLE.items():
        if getattr(rules, field_name):
            checks.append(RuleCheck(rule=field_name, met=False, reason=reason))

    return RuleEvaluation(met=all(c.met for c in checks), checks=tuple(checks))


__all__ = ["CompletionRules", "RuleCheck", "RuleEvaluation", "evaluate", "merge_rules"]
