"""Every choice the browser renders needs its Korean label, and it lives here."""

from __future__ import annotations

import re

from opic.core.survey import (
    GROUP_LABELS_KO,
    HOUSING_LABELS_KO,
    OCCUPATION_LABELS_KO,
    QUESTION_LABELS_KO,
    RECENT_COURSE_LABELS_KO,
    YES_NO_LABELS_KO,
    Housing,
    Occupation,
    RecentCourse,
    SurveyError,
    TopicGroup,
    ValidationIssue,
    describe_issue_ko,
)

ASCII_LETTER = re.compile(r"[A-Za-z]")

# One `detail` string per `SurveyError`, in the exact shape `validate_survey`
# actually produces — see the corresponding branches in `validate_survey`.
REPRESENTATIVE_DETAILS: dict[SurveyError, str] = {
    SurveyError.UNKNOWN_ITEM: "not_a_real_item",
    SurveyError.DUPLICATE_ITEM: "movies",
    SurveyError.TOO_FEW_ITEMS: "3/12",
    SurveyError.GROUP_MINIMUM: "sport: 0/1",
    SurveyError.MISSING_COURSE: "not a student",
    SurveyError.UNEXPECTED_COURSE: "language",
}


def test_every_occupation_has_a_korean_label():
    assert set(OCCUPATION_LABELS_KO) == set(Occupation)
    assert all(label.strip() for label in OCCUPATION_LABELS_KO.values())


def test_every_housing_option_has_a_korean_label():
    assert set(HOUSING_LABELS_KO) == set(Housing)


def test_every_topic_group_has_a_korean_label():
    assert set(GROUP_LABELS_KO) == set(TopicGroup)


def test_the_course_labels_already_there_still_cover_the_enum():
    assert set(RECENT_COURSE_LABELS_KO) == set(RecentCourse)


def test_every_survey_question_has_a_korean_stem():
    assert set(QUESTION_LABELS_KO) == {"occupation", "is_student", "recent_course", "housing"}
    assert all(label.strip() for label in QUESTION_LABELS_KO.values())


def test_yes_and_no_have_korean_labels():
    assert YES_NO_LABELS_KO[True] == "예"
    assert YES_NO_LABELS_KO[False] == "아니오"


def test_every_survey_error_has_a_korean_message_a_candidate_can_act_on():
    assert set(REPRESENTATIVE_DETAILS) == set(SurveyError)
    for error, detail in REPRESENTATIVE_DETAILS.items():
        message = describe_issue_ko(ValidationIssue(error, detail))
        assert message.strip()
        # A leaked enum name or id (both ASCII) is exactly what this guards
        # against — the message must read as a Korean sentence, not a code.
        assert not ASCII_LETTER.search(message), (error, message)
