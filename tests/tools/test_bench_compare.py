from __future__ import annotations

from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import DimensionScore, Evidence

from rater_bench import agreement, rewrite_overlap


def scores(levels: dict[Dimension, ActflLevel]) -> tuple[DimensionScore, ...]:
    return tuple(
        DimensionScore(dimension=d, level=levels[d], comment_ko="설명", evidence=())
        for d in Dimension
    )


def test_identical_ratings_agree_everywhere():
    both = {d: ActflLevel.IM2 for d in Dimension}
    result = agreement(scores(both), scores(both))
    assert result.exact == len(Dimension)
    assert result.within_one == len(Dimension)
    assert result.mean_gap == 0.0


def test_a_one_band_difference_is_not_exact_but_is_within_one():
    local = {d: ActflLevel.IM2 for d in Dimension}
    remote = dict(local)
    remote[Dimension.GRAMMAR] = ActflLevel.IM3
    result = agreement(scores(local), scores(remote))
    assert result.exact == len(Dimension) - 1
    assert result.within_one == len(Dimension)
    assert result.mean_gap == 1 / len(Dimension)


def test_the_gap_is_measured_in_bands_not_just_counted():
    local = {d: ActflLevel.NL for d in Dimension}
    remote = {d: ActflLevel.AL for d in Dimension}
    result = agreement(scores(local), scores(remote))
    assert result.exact == 0
    assert result.within_one == 0
    assert result.mean_gap == 8.0


def test_a_rewrite_of_the_quote_overlaps_heavily():
    assert rewrite_overlap("we take a bath there", "we took a bath there") > 0.6


def test_a_description_of_the_problem_shares_almost_nothing_with_the_quote():
    assert rewrite_overlap("we take a bath there", "The verb tense is incorrect.") < 0.2


def test_overlap_ignores_case_and_punctuation():
    assert rewrite_overlap("We take a bath.", "we take a bath") == 1.0
