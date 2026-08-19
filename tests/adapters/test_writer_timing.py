"""How long a full question set takes to write. Marked `models`: needs Ollama."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from opic.adapters.llm import OllamaClient
from opic.core.questions import EXAM_LENGTH, build_blueprint
from opic.core.survey import Housing, Occupation, RecentCourse, SurveyAnswers

TWELVE_ITEMS = (
    "movies", "clubbing", "live_shows", "concerts", "museums", "parks",
    "listening_music", "cooking", "yoga", "walking", "domestic_travel", "overseas_travel",
)


@pytest.mark.models
def test_write_full_question_set_timing(tmp_path: Path) -> None:
    answers = SurveyAnswers(
        occupation=Occupation.BUSINESS,
        is_student=False,
        housing=Housing.ALONE,
        selected_item_ids=TWELVE_ITEMS,
        recent_course=RecentCourse.LANGUAGE,
    )
    blueprint = build_blueprint(answers, self_assess_level=4, seed=7)

    elapsed = []
    for trial in range(3):
        started = time.monotonic()
        questions = OllamaClient().write(answers, blueprint)
        elapsed.append(time.monotonic() - started)
        assert len(questions) == EXAM_LENGTH

    (tmp_path / "timing.json").write_text(json.dumps(elapsed), encoding="utf-8")
    print(f"\nwrite() elapsed: {[round(e, 1) for e in elapsed]}")
