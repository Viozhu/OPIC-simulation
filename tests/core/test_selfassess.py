from __future__ import annotations

import pytest

from opic.core.rubric import ActflLevel
from opic.core.selfassess import (
    LEVEL_TO_TARGET,
    SELF_ASSESS_OPTIONS,
    target_level,
)


def test_there_are_exactly_six_options_numbered_in_order():
    assert [option.level for option in SELF_ASSESS_OPTIONS] == [1, 2, 3, 4, 5, 6]


def test_every_option_has_korean_text_and_a_sample_audio_id():
    for option in SELF_ASSESS_OPTIONS:
        assert option.description_ko.strip()
        assert option.sample_audio_id.strip()


def test_sample_audio_ids_are_unique():
    ids = [option.sample_audio_id for option in SELF_ASSESS_OPTIONS]
    assert len(ids) == len(set(ids))


def test_targets_rise_with_the_self_assessed_level():
    ranks = [LEVEL_TO_TARGET[level].rank for level in range(1, 7)]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 6


def test_target_level_maps_the_extremes():
    assert target_level(1) is ActflLevel.NL
    assert target_level(6) is ActflLevel.AL


@pytest.mark.parametrize("level", [0, 7, -1])
def test_target_level_rejects_levels_outside_the_scale(level):
    with pytest.raises(ValueError):
        target_level(level)
