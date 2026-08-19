from __future__ import annotations

import json
from pathlib import Path

import pytest

from opic.cli import load_survey, run_exam
from opic.core.questions import Question
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
        spoken = f"this is the answer for {audio.stem}".split()
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
        self.seen: list[tuple[str, str]] = []

    def rate(self, question, transcript, metrics) -> tuple[DimensionScore, ...]:
        self.seen.append((question.text_en, transcript.text))
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

    def fake_recorder(path: Path, seconds: int, device: str) -> Path:
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
    assert len(rater.seen) == 15
    for index, (asked, heard) in enumerate(rater.seen):
        assert asked == f"Question {index}?"
        assert f"answer-{index:02d}" in heard
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
        recorder=lambda path, seconds, device: (path.write_bytes(b"a"), path)[1],
        player=lambda path: None,
    )
    saved = json.loads((session / "result.json").read_text())
    assert saved["final_level"] == "IM2"
    assert len(saved["answers"]) == 15
    assert [a["question_en"] for a in saved["answers"]] == [
        f"Question {i}?" for i in range(15)
    ]
    for index, answer in enumerate(saved["answers"]):
        assert f"answer-{index:02d}" in answer["transcript"]["text"]


def survey_json(tmp_path, **overrides) -> Path:
    answers = valid_answers()
    payload = {
        "occupation": answers.occupation.value,
        "is_student": answers.is_student,
        "housing": answers.housing.value,
        "selected_item_ids": list(answers.selected_item_ids),
        "recent_course": answers.recent_course.value,
    }
    payload.update(overrides)
    path = tmp_path / "survey.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_a_valid_survey_file_loads(tmp_path):
    assert load_survey(survey_json(tmp_path)) == valid_answers()


def test_a_missing_field_is_named(tmp_path):
    path = survey_json(tmp_path)
    payload = json.loads(path.read_text())
    del payload["housing"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="housing"):
        load_survey(path)


def test_an_unknown_enum_value_lists_the_valid_ones(tmp_path):
    path = survey_json(tmp_path, occupation="astronaut")
    with pytest.raises(ValueError) as caught:
        load_survey(path)
    assert "astronaut" in str(caught.value)
    assert "business" in str(caught.value)


def test_malformed_json_names_the_file(tmp_path):
    path = tmp_path / "survey.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="survey.json"):
        load_survey(path)


def test_a_non_list_selection_is_refused(tmp_path):
    with pytest.raises(ValueError, match="selected_item_ids"):
        load_survey(survey_json(tmp_path, selected_item_ids=42))


def test_the_shipped_example_survey_is_valid():
    from opic.core.survey import validate_survey

    assert validate_survey(load_survey(Path("examples/survey.json"))) == ()


def test_a_scoring_failure_prints_one_line_instead_of_a_traceback(
    tmp_path, monkeypatch, capsys
):
    """A dead Ollama mid-exam must not surface a raw traceback to the candidate.

    `run_exam` raises a bare `RuntimeError` when nothing could be scored (see
    its docstring); `main()` must catch that and print the same friendly,
    one-line `error: ...` form it already uses for the other failure modes,
    not let the exception escape.
    """
    import opic.cli as cli

    def failing_run_exam(**kwargs):
        raise RuntimeError("no answer could be scored; is Ollama running?")

    monkeypatch.setattr(cli, "run_exam", failing_run_exam)

    exit_code = cli.main(
        [
            "--survey", str(survey_json(tmp_path)),
            "--level", "4",
            "--session", str(tmp_path / "session"),
        ]
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Traceback" not in out
    assert "error: no answer could be scored" in out
