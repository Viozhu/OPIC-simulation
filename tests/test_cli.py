from __future__ import annotations

import json
from pathlib import Path

from opic.cli import run_exam
from opic.core.questions import Question, QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import DimensionScore
from opic.core.survey import (
    SURVEY_ITEMS,
    Housing,
    Occupation,
    RecentCourse,
    SurveyAnswers,
    TopicGroup,
)
from opic.core.transcript import Span, Transcript, Word


def ids_for(group: TopicGroup, count: int) -> list[str]:
    return [item.id for item in SURVEY_ITEMS if item.group is group][:count]


def valid_answers() -> SurveyAnswers:
    return SurveyAnswers(
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


class FakeTts:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> Path:
        self.spoken.append(text)
        target = self.tmp / f"q{len(self.spoken)}.wav"
        target.write_bytes(b"audio")
        return target


class FakeStt:
    def transcribe(self, audio: Path) -> Transcript:
        spoken = "I went to the beach and we take a bath there".split()
        return Transcript(
            text=" ".join(spoken),
            words=tuple(
                Word(w, i * 0.4, i * 0.4 + 0.3, 0.9) for i, w in enumerate(spoken)
            ),
            speech_spans=(Span(0.0, 2.0), Span(3.0, 5.0)),
            duration_s=30.0,
        )


class FakeWriter:
    def write(self, answers, blueprint):
        return tuple(
            Question(slot=slot, text_en=f"Question {slot.index}?")
            for slot in blueprint
        )


class FakeRater:
    def __init__(self):
        self.calls = 0

    def rate(self, question, transcript, metrics) -> tuple[DimensionScore, ...]:
        self.calls += 1
        return tuple(
            DimensionScore(
                dimension=d,
                level=ActflLevel.IM2,
                comment_ko="좋습니다.",
                evidence=(),
            )
            for d in Dimension
        )


def test_a_full_exam_runs_end_to_end(tmp_path):
    tts, rater = FakeTts(tmp_path), FakeRater()
    recorded: list[Path] = []

    def fake_recorder(path: Path, seconds: int) -> Path:
        path.write_bytes(b"answer")
        recorded.append(path)
        return path

    played: list[Path] = []

    result = run_exam(
        answers=valid_answers(),
        self_assess_level=4,
        seed=7,
        session_dir=tmp_path / "session",
        tts=tts,
        stt=FakeStt(),
        writer=FakeWriter(),
        rater=rater,
        recorder=fake_recorder,
        player=played.append,
    )

    assert len(tts.spoken) == 15
    assert len(recorded) == 15
    assert len(played) == 15
    assert rater.calls == 15
    assert result.final_level is ActflLevel.IM2
    assert len(result.assessments) == 15
    assert result.by_topic


def test_the_session_directory_holds_the_result(tmp_path):
    session = tmp_path / "session"
    run_exam(
        answers=valid_answers(),
        self_assess_level=4,
        seed=7,
        session_dir=session,
        tts=FakeTts(tmp_path),
        stt=FakeStt(),
        writer=FakeWriter(),
        rater=FakeRater(),
        recorder=lambda path, seconds: (path.write_bytes(b"a"), path)[1],
        player=lambda path: None,
    )
    saved = json.loads((session / "result.json").read_text())
    assert saved["final_level"] == "IM2"
    assert len(saved["answers"]) == 15
    assert saved["answers"][0]["question_en"] == "Question 0?"
