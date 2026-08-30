from __future__ import annotations

import pytest

from opic.core.rubric import (
    DIMENSION_LABELS_KO,
    DIMENSION_WEIGHTS,
    ActflLevel,
    Dimension,
)


def test_levels_are_ordered_low_to_high():
    ranks = [level.rank for level in ActflLevel]
    assert ranks == sorted(ranks)
    assert [level.name for level in ActflLevel] == [
        "NL", "NM", "NH", "IL", "IM1", "IM2", "IM3", "IH", "AL",
    ]


def test_from_rank_round_trips():
    for level in ActflLevel:
        assert ActflLevel.from_rank(level.rank) is level


@pytest.mark.parametrize(
    ("rank", "expected"),
    [(-5, ActflLevel.NL), (99, ActflLevel.AL)],
)
def test_from_rank_clamps_out_of_range(rank, expected):
    assert ActflLevel.from_rank(rank) is expected


def test_dimension_weights_cover_every_dimension_and_sum_to_one():
    assert set(DIMENSION_WEIGHTS) == set(Dimension)
    assert sum(DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_dimension_has_a_korean_label():
    assert set(DIMENSION_LABELS_KO) == set(Dimension)
    assert all(label.strip() for label in DIMENSION_LABELS_KO.values())


def test_every_question_type_has_a_korean_label():
    from opic.core.questions import QUESTION_TYPE_LABELS_KO, QuestionType

    assert set(QUESTION_TYPE_LABELS_KO) == set(QuestionType)
    assert all(label.strip() for label in QUESTION_TYPE_LABELS_KO.values())
    assert QUESTION_TYPE_LABELS_KO[QuestionType.ROLEPLAY_FOLLOWUP] == "롤플레이 (돌발 상황)"
