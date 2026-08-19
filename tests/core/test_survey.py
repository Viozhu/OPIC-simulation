from __future__ import annotations

import pytest

from opic.core.survey import (
    GROUP_MINIMUMS,
    ITEMS_BY_ID,
    MIN_TOTAL_ITEMS,
    SURVEY_ITEMS,
    Housing,
    Occupation,
    SurveyAnswers,
    SurveyError,
    TopicGroup,
    selected_items,
    validate_survey,
)


def ids_for(group: TopicGroup, count: int) -> list[str]:
    return [item.id for item in SURVEY_ITEMS if item.group is group][:count]


def valid_selection() -> tuple[str, ...]:
    picks = (
        ids_for(TopicGroup.LEISURE, 4)
        + ids_for(TopicGroup.HOBBY, 4)
        + ids_for(TopicGroup.SPORT, 2)
        + ids_for(TopicGroup.TRAVEL, 2)
    )
    assert len(picks) == 12
    return tuple(picks)


def answers_with(selection: tuple[str, ...]) -> SurveyAnswers:
    return SurveyAnswers(
        occupation=Occupation.BUSINESS,
        is_student=False,
        housing=Housing.WITH_FAMILY,
        selected_item_ids=selection,
    )


def test_catalog_ids_are_unique_and_indexed():
    ids = [item.id for item in SURVEY_ITEMS]
    assert len(ids) == len(set(ids))
    assert set(ITEMS_BY_ID) == set(ids)


def test_every_group_has_enough_items_to_satisfy_its_minimum():
    for group, minimum in GROUP_MINIMUMS.items():
        available = [item for item in SURVEY_ITEMS if item.group is group]
        assert len(available) >= minimum


def test_every_item_carries_both_labels():
    for item in SURVEY_ITEMS:
        assert item.label_ko.strip()
        assert item.label_en.strip()


def test_a_full_selection_is_valid():
    assert validate_survey(answers_with(valid_selection())) == ()


def test_fewer_than_the_minimum_items_is_rejected():
    selection = valid_selection()[: MIN_TOTAL_ITEMS - 1]
    issues = validate_survey(answers_with(selection))
    assert SurveyError.TOO_FEW_ITEMS in {issue.error for issue in issues}


def test_missing_a_group_minimum_is_rejected():
    without_travel = tuple(
        item_id
        for item_id in valid_selection()
        if ITEMS_BY_ID[item_id].group is not TopicGroup.TRAVEL
    )
    padded = without_travel + tuple(ids_for(TopicGroup.SPORT, 4)[2:])
    issues = validate_survey(answers_with(padded))
    assert SurveyError.GROUP_MINIMUM in {issue.error for issue in issues}


def test_an_unknown_item_id_is_rejected():
    issues = validate_survey(answers_with(valid_selection() + ("nope",)))
    assert SurveyError.UNKNOWN_ITEM in {issue.error for issue in issues}


def test_selected_items_returns_catalog_entries_in_selection_order():
    selection = valid_selection()
    items = selected_items(answers_with(selection))
    assert tuple(item.id for item in items) == selection


def test_selected_items_raises_on_unknown_id():
    with pytest.raises(KeyError):
        selected_items(answers_with(("nope",)))
