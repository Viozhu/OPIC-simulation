from __future__ import annotations

import pytest

from opic.core.questions import (
    COMBO_COUNT,
    COMBO_TYPES,
    EXAM_LENGTH,
    QuestionType,
    build_blueprint,
)
from opic.core.selfassess import target_level
from opic.core.survey import (
    SURVEY_ITEMS,
    Housing,
    Occupation,
    SurveyAnswers,
    TopicGroup,
)


def ids_for(group: TopicGroup, count: int) -> list[str]:
    return [item.id for item in SURVEY_ITEMS if item.group is group][:count]


def valid_answers() -> SurveyAnswers:
    picks = (
        ids_for(TopicGroup.LEISURE, 4)
        + ids_for(TopicGroup.HOBBY, 4)
        + ids_for(TopicGroup.SPORT, 2)
        + ids_for(TopicGroup.TRAVEL, 2)
    )
    return SurveyAnswers(
        occupation=Occupation.BUSINESS,
        is_student=False,
        housing=Housing.WITH_FAMILY,
        selected_item_ids=tuple(picks),
    )


def test_blueprint_has_the_exam_length():
    blueprint = build_blueprint(valid_answers(), self_assess_level=4, seed=7)
    assert len(blueprint) == EXAM_LENGTH
    assert [slot.index for slot in blueprint] == list(range(EXAM_LENGTH))


def test_blueprint_opens_with_a_self_introduction_and_closes_with_role_play():
    blueprint = build_blueprint(valid_answers(), self_assess_level=4, seed=7)
    assert blueprint[0].qtype is QuestionType.SELF_INTRO
    assert blueprint[0].topic_id is None
    assert blueprint[-2].qtype is QuestionType.ROLEPLAY_SETUP
    assert blueprint[-1].qtype is QuestionType.ROLEPLAY_FOLLOWUP


def test_combos_run_description_then_habit_then_experience_on_one_topic():
    blueprint = build_blueprint(valid_answers(), self_assess_level=4, seed=7)
    combos = [slot for slot in blueprint if slot.combo_id is not None]
    assert len(combos) == COMBO_COUNT * len(COMBO_TYPES)
    for combo_id in range(COMBO_COUNT):
        group = [slot for slot in combos if slot.combo_id == combo_id]
        assert [slot.qtype for slot in group] == list(COMBO_TYPES)
        assert len({slot.topic_id for slot in group}) == 1


def test_each_combo_uses_a_distinct_selected_topic():
    answers = valid_answers()
    blueprint = build_blueprint(answers, self_assess_level=4, seed=7)
    topics = {
        slot.combo_id: slot.topic_id
        for slot in blueprint
        if slot.combo_id is not None
    }
    assert len(set(topics.values())) == COMBO_COUNT
    assert set(topics.values()) <= set(answers.selected_item_ids)


def test_only_the_last_combo_is_advanced_and_aims_one_band_higher():
    blueprint = build_blueprint(valid_answers(), self_assess_level=4, seed=7)
    base = target_level(4)
    advanced = [slot for slot in blueprint if slot.advanced]
    assert {slot.combo_id for slot in advanced} == {COMBO_COUNT - 1}
    assert all(slot.target.rank == base.rank + 1 for slot in advanced)
    plain = [
        slot for slot in blueprint if slot.combo_id is not None and not slot.advanced
    ]
    assert all(slot.target is base for slot in plain)


def test_the_same_seed_produces_the_same_blueprint():
    first = build_blueprint(valid_answers(), self_assess_level=4, seed=7)
    second = build_blueprint(valid_answers(), self_assess_level=4, seed=7)
    assert first == second


def test_different_seeds_can_pick_different_topics():
    answers = valid_answers()
    seen = {
        tuple(
            slot.topic_id for slot in build_blueprint(answers, 4, seed) if slot.combo_id is not None
        )
        for seed in range(20)
    }
    assert len(seen) > 1


def test_an_invalid_survey_is_refused():
    answers = SurveyAnswers(
        occupation=Occupation.TEACHER,
        is_student=False,
        housing=Housing.ALONE,
        selected_item_ids=("movies",),
    )
    with pytest.raises(ValueError):
        build_blueprint(answers, self_assess_level=3, seed=1)
