"""Every choice the browser renders needs its Korean label, and it lives here."""

from __future__ import annotations

from opic.core.survey import (
    GROUP_LABELS_KO,
    HOUSING_LABELS_KO,
    OCCUPATION_LABELS_KO,
    RECENT_COURSE_LABELS_KO,
    Housing,
    Occupation,
    RecentCourse,
    TopicGroup,
)


def test_every_occupation_has_a_korean_label():
    assert set(OCCUPATION_LABELS_KO) == set(Occupation)
    assert all(label.strip() for label in OCCUPATION_LABELS_KO.values())


def test_every_housing_option_has_a_korean_label():
    assert set(HOUSING_LABELS_KO) == set(Housing)


def test_every_topic_group_has_a_korean_label():
    assert set(GROUP_LABELS_KO) == set(TopicGroup)


def test_the_course_labels_already_there_still_cover_the_enum():
    assert set(RECENT_COURSE_LABELS_KO) == set(RecentCourse)
