from __future__ import annotations

from opic.core.metrics import compute_metrics
from opic.core.questions import EXAM_LENGTH, build_blueprint
from opic.core.transcript import Span, Transcript, Word
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import (
    AnswerAssessment,
    DimensionScore,
    Evidence,
    aggregate,
)
from opic.core.survey import (
    SURVEY_ITEMS,
    Housing,
    Occupation,
    RecentCourse,
    SurveyAnswers,
    TopicGroup,
    validate_survey,
)


def ids_for(group: TopicGroup, count: int) -> list[str]:
    return [item.id for item in SURVEY_ITEMS if item.group is group][:count]


def test_a_full_run_goes_from_survey_to_a_final_level():
    answers = SurveyAnswers(
        occupation=Occupation.BUSINESS,
        is_student=False,
        housing=Housing.ALONE,
        selected_item_ids=tuple(
            ids_for(TopicGroup.LEISURE, 4)
            + ids_for(TopicGroup.HOBBY, 4)
            + ids_for(TopicGroup.SPORT, 2)
            + ids_for(TopicGroup.TRAVEL, 2)
        ),
        recent_course=RecentCourse.LANGUAGE,
    )
    assert validate_survey(answers) == ()

    blueprint = build_blueprint(answers, self_assess_level=4, seed=42)
    assert len(blueprint) == EXAM_LENGTH

    spoken = "I usually go to the beach on weekends".split()
    words = tuple(
        Word(text=text, start=i * 0.4, end=i * 0.4 + 0.3, probability=0.88)
        for i, text in enumerate(spoken)
    )
    metrics = compute_metrics(
        Transcript(
            text=" ".join(spoken),
            words=words,
            speech_spans=(Span(0.0, 3.1), Span(5.0, 8.0)),
            duration_s=30.0,
        )
    )

    assessments = [
        AnswerAssessment(
            question_index=slot.index,
            dimension_scores=tuple(
                DimensionScore(
                    dimension=dimension,
                    level=ActflLevel.IM2,
                    comment_ko="문장 연결이 자연스럽습니다.",
                    evidence=(
                        Evidence(
                            quote="I usually go to the beach on weekends",
                            issue_ko="시제 사용은 적절합니다.",
                            correction_en="I usually go to the beach on weekends.",
                        ),
                    ),
                )
                for dimension in Dimension
            ),
            metrics=metrics,
        )
        for slot in blueprint
    ]

    result = aggregate(blueprint, assessments)
    assert result.final_level is ActflLevel.IM2
    assert len(result.assessments) == EXAM_LENGTH
    assert result.pronunciation.indicative is True
    assert {dim for dim, _ in result.dimension_levels} == set(Dimension)
