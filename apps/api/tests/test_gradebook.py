"""Pure-function tests for the gradebook fold (`services/gradebook.py`, P18)
— no Postgres, no fixtures beyond plain Python values, same tier as
`test_completion.py`.

The cases that matter here are the dishonest-reporting ones: a half-marked
course must not report every learner as failing, an unmarked item must not
read as a zero, and a nonsensical denominator must not take a whole report
down with it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from src.services.gradebook import AchievementItem, build, validate_score

pytestmark = pytest.mark.unit


def item(
    *,
    kind: str = "quiz",
    item_id: str = "i1",
    title: str = "Item",
    weight: str = "1",
    max_score: str = "100",
    score: str | None = None,
    passed: bool | None = None,
) -> AchievementItem:
    return AchievementItem(
        kind=kind,
        item_id=item_id,
        title=title,
        weight=Decimal(weight),
        max_score=Decimal(max_score),
        score=None if score is None else Decimal(score),
        passed=passed,
    )


class TestPercentage:
    def test_single_graded_item_is_its_own_percentage(self) -> None:
        book = build([item(score="73")])

        assert book.percentage == Decimal("73.00")
        assert book.graded_weight == Decimal("1")
        assert book.total_weight == Decimal("1")

    def test_equal_weights_average(self) -> None:
        book = build([item(item_id="a", score="80"), item(item_id="b", score="60")])

        assert book.percentage == Decimal("70.00")

    def test_weight_actually_weighs(self) -> None:
        # 3:1 in favour of the 80 -> (3*0.8 + 1*0.6) / 4 = 0.75
        book = build(
            [
                item(item_id="a", score="80", weight="3"),
                item(item_id="b", score="60", weight="1"),
            ]
        )

        assert book.percentage == Decimal("75.00")

    def test_max_score_is_the_denominator_not_a_constant_hundred(self) -> None:
        book = build([item(score="15", max_score="20")])

        assert book.percentage == Decimal("75.00")

    def test_mixed_denominators_are_normalised_before_weighting(self) -> None:
        # A 5-mark item and a 100-mark item at equal weight must count
        # equally, not 5:100. Getting this wrong makes small quizzes
        # invisible.
        book = build(
            [
                item(item_id="a", score="5", max_score="5"),
                item(item_id="b", score="50", max_score="100"),
            ]
        )

        assert book.percentage == Decimal("75.00")

    def test_rounds_half_up_to_two_places(self) -> None:
        # 2/3 -> 66.666... must not round-half-even down to 66.66
        book = build([item(score="2", max_score="3")])

        assert book.percentage == Decimal("66.67")

    def test_a_marked_zero_is_a_zero(self) -> None:
        book = build([item(score="0")])

        assert book.percentage == Decimal("0.00")
        assert book.graded and not book.ungraded


class TestUngraded:
    def test_ungraded_items_are_excluded_rather_than_counted_as_zero(self) -> None:
        # The whole point: a course half-marked reports 80%, not 40%.
        book = build([item(item_id="a", score="80"), item(item_id="b")])

        assert book.percentage == Decimal("80.00")
        assert [i.item_id for i in book.ungraded] == ["b"]
        assert book.graded_weight == Decimal("1")
        assert book.total_weight == Decimal("2")

    def test_nothing_graded_yields_no_percentage_not_zero(self) -> None:
        book = build([item(item_id="a"), item(item_id="b")])

        assert book.percentage is None
        assert book.graded == ()
        assert len(book.ungraded) == 2

    def test_empty_gradebook_is_not_a_failure(self) -> None:
        book = build([])

        assert book.percentage is None
        assert book.total_weight == Decimal("0")
        assert book.is_complete is False

    def test_is_complete_only_when_every_item_is_marked(self) -> None:
        assert build([item(score="50")]).is_complete is True
        assert build([item(item_id="a", score="50"), item(item_id="b")]).is_complete is False

    def test_is_complete_says_nothing_about_passing(self) -> None:
        # Guards against a future caller reading is_complete as "passed".
        book = build([item(score="0")])

        assert book.is_complete is True
        assert book.percentage == Decimal("0.00")


class TestDegenerateInput:
    def test_zero_max_score_is_treated_as_ungraded_not_a_crash(self) -> None:
        # A misconfigured item must not divide by zero and take the whole
        # report down with it.
        book = build(
            [
                item(item_id="ok", score="50"),
                item(item_id="bad", score="5", max_score="0"),
            ]
        )

        assert book.percentage == Decimal("50.00")
        assert [i.item_id for i in book.ungraded] == ["bad"]

    def test_negative_max_score_is_also_ungraded(self) -> None:
        book = build([item(score="5", max_score="-10")])

        assert book.percentage is None

    def test_score_above_max_is_reported_as_given(self) -> None:
        # The write path (validate_score) is what refuses these; the fold
        # must not silently clamp historical data and hide a bad mark.
        book = build([item(score="120", max_score="100")])

        assert book.percentage == Decimal("120.00")

    def test_items_are_returned_in_the_order_given(self) -> None:
        book = build([item(item_id="c"), item(item_id="a", score="1"), item(item_id="b")])

        assert [i.item_id for i in book.items] == ["c", "a", "b"]


class TestValidateScore:
    def test_accepts_a_mark_within_range(self) -> None:
        assert validate_score(Decimal("73.5"), 100) == Decimal("73.5")

    def test_accepts_the_boundaries(self) -> None:
        assert validate_score(Decimal("0"), 100) == Decimal("0")
        assert validate_score(Decimal("100"), 100) == Decimal("100")

    def test_none_passes_through_as_not_marked(self) -> None:
        assert validate_score(None, 100) is None

    def test_rejects_a_negative_mark(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            validate_score(Decimal("-1"), 100)

    def test_rejects_a_mark_above_the_assignments_maximum(self) -> None:
        with pytest.raises(ValueError, match="maximum of 50"):
            validate_score(Decimal("51"), 50)

    def test_rejects_marking_against_an_unusable_maximum(self) -> None:
        with pytest.raises(ValueError, match="no usable maximum"):
            validate_score(Decimal("1"), 0)
