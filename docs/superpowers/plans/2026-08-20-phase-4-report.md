# Phase 4 — The Report: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the raw result screen into a report that explains the grade — per-dimension levels with the candidate's own quoted mistakes, the words the recogniser could not catch, breakdowns by question type and topic, and an answer-by-answer detail — in Korean, in the browser and on the CLI.

**Architecture:** Python builds a view model (`core/report.py`, pure), the session layer serialises it, a new route serves it, and `done.js` only paints. The CLI prints the same model as text. Nothing about scoring changes: `scoring.py` gains one read-only helper so the report can explain the weak-dimension cap.

**Tech Stack:** Python 3.13+, dataclasses, FastAPI, pytest, vanilla ES modules (no build step, no JS test runner).

**Spec:** `docs/superpowers/specs/2026-08-20-phase-4-report-design.md`

## Global Constraints

- Run tests with `uv run --extra dev pytest`.
- `src/opic/core/**` must not import infrastructure. `tests/test_core_purity.py` forbids: `fastapi`, `uvicorn`, `httpx`, `requests`, `ollama`, `faster_whisper`, `piper`, `sqlite3`. Formatting text in `core` is allowed.
- All user-facing strings are Korean. English survives only inside quoted candidate speech (`Evidence.quote`), the corrections (`Evidence.correction_en`) and the question text (`Question.text_en`).
- `GET /api/sessions/{id}/result` must keep returning exactly what it returns today. `tests/web/test_answer_routes.py` must pass unedited.
- `LOW_CONFIDENCE_THRESHOLD = 0.6` lives in `src/opic/core/metrics.py`. Import it; never re-declare the number.
- `WEAK_DIMENSION_GAP = 3` lives in `src/opic/core/scoring.py`.
- Dataclasses in `core` are `@dataclass(frozen=True, slots=True)`, matching every existing one.
- Commit after every task. Branch: `feat/phase-4-report`.

---

### Task 1: Korean labels for question types

**Files:**
- Modify: `src/opic/core/rubric.py` (append after `DIMENSION_LABELS_KO`, ends line 54)
- Test: `tests/core/test_rubric.py`

**Interfaces:**
- Consumes: `QuestionType` from `opic.core.questions`
- Produces: `QUESTION_TYPE_LABELS_KO: dict[QuestionType, str]`

Note: `rubric.py` currently imports nothing from `questions.py`. `questions.py` imports `rubric.py` (for `ActflLevel`). Importing `QuestionType` into `rubric.py` would be a circular import. **Put the table in `questions.py` instead**, next to `QuestionType`, and have the report import it from there. The spec says "next to `DIMENSION_LABELS_KO`"; the import cycle overrides that, and this note is why.

- [ ] **Step 1: Write the failing test**

In `tests/core/test_rubric.py`, append:

```python
def test_every_question_type_has_a_korean_label():
    from opic.core.questions import QUESTION_TYPE_LABELS_KO, QuestionType

    assert set(QUESTION_TYPE_LABELS_KO) == set(QuestionType)
    assert all(label.strip() for label in QUESTION_TYPE_LABELS_KO.values())
    assert QUESTION_TYPE_LABELS_KO[QuestionType.ROLEPLAY_FOLLOWUP] == "롤플레이 (후속)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_rubric.py::test_every_question_type_has_a_korean_label -v`
Expected: FAIL with `ImportError: cannot import name 'QUESTION_TYPE_LABELS_KO'`

- [ ] **Step 3: Write minimal implementation**

In `src/opic/core/questions.py`, after the `QuestionType` enum:

```python
QUESTION_TYPE_LABELS_KO: dict[QuestionType, str] = {
    QuestionType.SELF_INTRO: "자기소개",
    QuestionType.DESCRIPTION: "묘사",
    QuestionType.HABIT: "습관·일상",
    QuestionType.EXPERIENCE: "경험",
    QuestionType.ROLEPLAY_SETUP: "롤플레이 (상황 설정)",
    QuestionType.ROLEPLAY_FOLLOWUP: "롤플레이 (후속)",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_rubric.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/questions.py tests/core/test_rubric.py
git commit -m "feat(core): korean labels for the six question types"
```

---

### Task 2: `limiting_dimension` — say which dimension capped the grade

**Files:**
- Modify: `src/opic/core/scoring.py:128-194` (`aggregate`) and add a new public function
- Test: `tests/core/test_scoring.py`

**Interfaces:**
- Consumes: `_weighted_rank`, `_capped`, `_level_for_answers`, `dimension_level` (all already in `scoring.py`)
- Produces:
  - `pre_cap_rank(blueprint: Sequence[QuestionSlot], assessments: Sequence[AnswerAssessment]) -> int`
  - `limiting_dimension(blueprint: Sequence[QuestionSlot], assessments: Sequence[AnswerAssessment]) -> tuple[Dimension, ActflLevel] | None`

`aggregate` currently computes the pre-cap rank inline (weighted rank, then the advanced-combo raise, `scoring.py:156-162`). Extract that into `pre_cap_rank` and have **both** `aggregate` and `limiting_dimension` call it, so the rule exists once. This is the point of the task — a second copy would drift.

Tie-break: if two dimensions share the weakest rank, return the first in `Dimension` declaration order. Deterministic, and tested.

- [ ] **Step 1: Write the failing test**

In `tests/core/test_scoring.py`, append (the module already has `slot`, `blueprint_of`, `assessment` helpers — reuse them):

```python
from opic.core.scoring import limiting_dimension


def test_no_limiting_dimension_when_the_cap_did_not_fire():
    level = {d: ActflLevel.IM2 for d in Dimension}
    assessments = [assessment(i, level) for i in range(3)]
    assert limiting_dimension(blueprint_of(3), assessments) is None


def test_the_limiting_dimension_is_the_weak_one_and_reports_the_uncapped_level():
    level = {d: ActflLevel.IH for d in Dimension}
    level[Dimension.GRAMMAR] = ActflLevel.NH
    assessments = [assessment(i, level) for i in range(3)]

    limiting = limiting_dimension(blueprint_of(3), assessments)

    assert limiting is not None
    dimension, without_cap = limiting
    assert dimension is Dimension.GRAMMAR
    assert without_cap.rank > aggregate(blueprint_of(3), assessments).final_level.rank


def test_a_tie_for_weakest_resolves_in_dimension_declaration_order():
    level = {d: ActflLevel.IH for d in Dimension}
    level[Dimension.GRAMMAR] = ActflLevel.NH
    level[Dimension.VOCABULARY] = ActflLevel.NH
    assessments = [assessment(i, level) for i in range(3)]

    dimension, _ = limiting_dimension(blueprint_of(3), assessments)

    assert dimension is Dimension.GRAMMAR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_scoring.py -k limiting -v`
Expected: FAIL with `ImportError: cannot import name 'limiting_dimension'`

- [ ] **Step 3: Write minimal implementation**

In `src/opic/core/scoring.py`, add after `_capped`:

```python
def pre_cap_rank(
    blueprint: Sequence[QuestionSlot],
    assessments: Sequence[AnswerAssessment],
) -> int:
    """The rank before the weak-dimension cap: weighted mean, then any raise."""
    slots = {slot.index: slot for slot in blueprint}
    rank = _weighted_rank(assessments)
    advanced = [a for a in assessments if slots[a.question_index].advanced]
    if advanced:
        stretch = _level_for_answers(advanced)
        if stretch.rank > rank:
            rank = min(rank + 1, stretch.rank)
    return rank


def limiting_dimension(
    blueprint: Sequence[QuestionSlot],
    assessments: Sequence[AnswerAssessment],
) -> tuple[Dimension, ActflLevel] | None:
    """The dimension that cost a band, and the level without that cap.

    `None` when the cap did not fire. Read-only: it changes no score, it only
    explains one. Ties for weakest resolve in `Dimension` declaration order.
    """
    if not assessments:
        return None
    rank = pre_cap_rank(blueprint, assessments)
    if _capped(rank, assessments) == rank:
        return None
    weakest = min(Dimension, key=lambda d: dimension_level(assessments, d).rank)
    return weakest, ActflLevel.from_rank(rank)
```

Then replace `scoring.py:156-162` inside `aggregate`:

```python
    rank = pre_cap_rank(blueprint, assessments)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_scoring.py -v`
Expected: PASS — including every pre-existing test, which is what proves the extraction did not change `aggregate`.

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/scoring.py tests/core/test_scoring.py
git commit -m "feat(core): expose which dimension capped the grade"
```

---

### Task 3: The report model and its header

**Files:**
- Create: `src/opic/core/report.py`
- Test: `tests/core/test_report.py` (create)

**Interfaces:**
- Consumes: `ExamResult`, `Evidence` (`opic.core.scoring`), `Question` (`opic.core.questions`), `DIMENSION_WEIGHTS`, `DIMENSION_LABELS_KO`, `ActflLevel`, `Dimension` (`opic.core.rubric`), `limiting_dimension` (Task 2)
- Produces: `MetricSummary`, `EvidenceRef`, `DimensionSummary`, `DimensionDetail`, `UnclearWord`, `AnswerReport`, `LimitingDimension`, `Report`, and `build_report(result, questions, unreadable=()) -> Report`

This task builds the dataclasses plus the header fields and the dimension summaries. Tasks 4 and 5 fill `unclear`, the breakdowns, `averages` and `answers`; until then those fields are empty tuples / `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_report.py`. Reuse the fixture helpers from `tests/core/test_scoring.py` by importing them:

```python
from __future__ import annotations

from opic.core.questions import QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.report import build_report
from opic.core.scoring import aggregate

from tests.core.test_scoring import assessment, blueprint_of, slot


def questions_of(n: int):
    from opic.core.questions import Question

    return tuple(
        Question(slot=slot(i, QuestionType.DESCRIPTION, "movies"), text_en=f"Question {i}")
        for i in range(n)
    )


def report_of(n: int, level: dict | None = None):
    level = level or {d: ActflLevel.IM2 for d in Dimension}
    assessments = [assessment(i, level) for i in range(n)]
    result = aggregate(blueprint_of(n), assessments)
    return build_report(result, questions_of(n))


def test_the_header_counts_scored_against_expected():
    report = report_of(3)
    assert report.scored_answers == 3
    assert report.expected_answers == 3
    assert report.final_level is ActflLevel.IM2


def test_dimensions_come_in_descending_weight_order():
    report = report_of(3)
    weights = [d.weight for d in report.dimensions]
    assert weights == sorted(weights, reverse=True)
    assert report.dimensions[0].dimension is Dimension.FLUENCY
    assert report.dimensions[0].label_ko == "유창성"


def test_no_limiting_dimension_when_the_cap_did_not_fire():
    assert report_of(3).limiting is None


def test_the_limiting_dimension_is_named_in_korean():
    level = {d: ActflLevel.IH for d in Dimension}
    level[Dimension.GRAMMAR] = ActflLevel.NH
    report = report_of(3, level)
    assert report.limiting is not None
    assert report.limiting.label_ko == "문법"
    assert report.limiting.without_cap.rank > report.final_level.rank
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.core.report'`

- [ ] **Step 3: Write minimal implementation**

Create `src/opic/core/report.py`:

```python
"""The exam result as something a candidate can read.

Everything here is derived — no score is computed, no rule is re-decided. The
browser and the CLI both render this model, so what the candidate is shown is
decided exactly once.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from opic.core.questions import QUESTION_TYPE_LABELS_KO, Question, QuestionType
from opic.core.rubric import (
    DIMENSION_LABELS_KO,
    DIMENSION_WEIGHTS,
    ActflLevel,
    Dimension,
)
from opic.core.scoring import Evidence, ExamResult, limiting_dimension


@dataclass(frozen=True, slots=True)
class MetricSummary:
    duration_s: float
    word_count: float
    words_per_minute: float
    pause_ratio: float
    mean_utterance_length: float


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    quote: str
    issue_ko: str
    correction_en: str
    answer_index: int


@dataclass(frozen=True, slots=True)
class DimensionSummary:
    dimension: Dimension
    label_ko: str
    weight: float
    level: ActflLevel
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class DimensionDetail:
    dimension: Dimension
    label_ko: str
    level: ActflLevel
    comment_ko: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class UnclearWord:
    text: str
    probability: float
    context: str
    answer_index: int


@dataclass(frozen=True, slots=True)
class AnswerReport:
    index: int
    question_en: str
    qtype_label_ko: str
    topic_label_ko: str | None
    state: str
    transcript_text: str
    metrics: MetricSummary | None
    scores: tuple[DimensionDetail, ...]


@dataclass(frozen=True, slots=True)
class LimitingDimension:
    dimension: Dimension
    label_ko: str
    level: ActflLevel
    without_cap: ActflLevel


@dataclass(frozen=True, slots=True)
class Report:
    final_level: ActflLevel
    scored_answers: int
    expected_answers: int
    limiting: LimitingDimension | None
    dimensions: tuple[DimensionSummary, ...]
    unclear: tuple[UnclearWord, ...]
    by_type: tuple[tuple[QuestionType, str, ActflLevel], ...]
    by_topic: tuple[tuple[str, str, ActflLevel], ...]
    averages: MetricSummary | None
    answers: tuple[AnswerReport, ...]


def build_report(
    result: ExamResult,
    questions: Sequence[Question],
    unreadable: Sequence[int] = (),
) -> Report:
    levels = dict(result.dimension_levels)
    blueprint = tuple(q.slot for q in questions if q.slot.index in {
        a.question_index for a in result.assessments
    })
    limiting = limiting_dimension(blueprint, result.assessments)
    return Report(
        final_level=result.final_level,
        scored_answers=len(result.assessments),
        expected_answers=len(questions),
        limiting=(
            LimitingDimension(
                dimension=limiting[0],
                label_ko=DIMENSION_LABELS_KO[limiting[0]],
                level=levels[limiting[0]],
                without_cap=limiting[1],
            )
            if limiting is not None
            else None
        ),
        dimensions=tuple(
            DimensionSummary(
                dimension=dimension,
                label_ko=DIMENSION_LABELS_KO[dimension],
                weight=weight,
                level=levels[dimension],
                evidence=_evidence_for(result, dimension),
            )
            for dimension, weight in sorted(
                DIMENSION_WEIGHTS.items(), key=lambda pair: -pair[1]
            )
        ),
        unclear=(),
        by_type=(),
        by_topic=(),
        averages=None,
        answers=(),
    )


def _evidence_for(result: ExamResult, dimension: Dimension) -> tuple[EvidenceRef, ...]:
    found = []
    for assessment in result.assessments:
        for score in assessment.dimension_scores:
            if score.dimension is not dimension:
                continue
            for item in score.evidence:
                found.append(
                    EvidenceRef(
                        quote=item.quote,
                        issue_ko=item.issue_ko,
                        correction_en=item.correction_en,
                        answer_index=assessment.question_index,
                    )
                )
    return tuple(found)
```

Note: `sorted(..., key=lambda pair: -pair[1])` is stable, so equal weights keep `Dimension` declaration order — 문법, 어휘, 구성력 all sit at 0.20 and must not shuffle between runs.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_report.py tests/test_core_purity.py -v`
Expected: PASS. The purity test must pass too — `report.py` is new core code.

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/report.py tests/core/test_report.py
git commit -m "feat(core): the report model, its header and dimension summaries"
```

---

### Task 4: The words the recogniser did not catch

**Files:**
- Modify: `src/opic/core/report.py`
- Test: `tests/core/test_report.py`

**Interfaces:**
- Consumes: `LOW_CONFIDENCE_THRESHOLD` from `opic.core.metrics`, `Transcript.words`
- Produces: `Report.unclear` populated; helper `_unclear_words(result) -> tuple[UnclearWord, ...]`

Context is the five words before and the five after, from the word stream. Not sentence splitting — see the spec §7.3 for why.

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_report.py`:

```python
from opic.core.transcript import Span, Transcript, Word


def transcript_with_a_mumble() -> Transcript:
    spoken = "I went to the beach and we take a bath there last summer".split()
    words = []
    for i, text in enumerate(spoken):
        probability = 0.4 if text == "bath" else 0.95
        words.append(Word(text, i * 0.4, i * 0.4 + 0.3, probability))
    return Transcript(
        text=" ".join(spoken),
        words=tuple(words),
        speech_spans=(Span(0.0, len(spoken) * 0.4),),
        duration_s=30.0,
    )


def test_unclear_words_are_listed_with_their_context_and_answer():
    level = {d: ActflLevel.IM2 for d in Dimension}
    assessments = [assessment(0, level)]
    object.__setattr__(assessments[0], "transcript", transcript_with_a_mumble())
    result = aggregate(blueprint_of(1), assessments)

    report = build_report(result, questions_of(1))

    assert [w.text for w in report.unclear] == ["bath"]
    assert report.unclear[0].answer_index == 0
    assert "we take a bath there last" in report.unclear[0].context


def test_no_unclear_words_gives_an_empty_tuple_not_a_placeholder():
    assert report_of(3).unclear == ()
```

If `AnswerAssessment` is frozen with slots, `object.__setattr__` will not work; build the assessment directly instead:

```python
from opic.core.scoring import AnswerAssessment, DimensionScore
from tests.core.test_scoring import metrics


def mumbled_assessment(index: int) -> AnswerAssessment:
    return AnswerAssessment(
        question=questions_of(index + 1)[index],
        transcript=transcript_with_a_mumble(),
        dimension_scores=tuple(
            DimensionScore(dimension=d, level=ActflLevel.IM2, comment_ko="괜찮습니다", evidence=())
            for d in Dimension
        ),
        metrics=metrics(),
    )
```

Use whichever of the two the dataclass allows; prefer building it directly.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_report.py -k unclear -v`
Expected: FAIL — `report.unclear` is `()` while the test expects `["bath"]`

- [ ] **Step 3: Write minimal implementation**

In `src/opic/core/report.py`, add the import and the helper, and set `unclear=_unclear_words(result)` in `build_report`:

```python
from opic.core.metrics import LOW_CONFIDENCE_THRESHOLD

CONTEXT_WORDS = 5


def _unclear_words(result: ExamResult) -> tuple[UnclearWord, ...]:
    found = []
    for assessment in result.assessments:
        words = assessment.transcript.words
        for position, word in enumerate(words):
            if word.probability >= LOW_CONFIDENCE_THRESHOLD:
                continue
            start = max(0, position - CONTEXT_WORDS)
            end = min(len(words), position + CONTEXT_WORDS + 1)
            found.append(
                UnclearWord(
                    text=word.text,
                    probability=word.probability,
                    context=" ".join(w.text for w in words[start:end]),
                    answer_index=assessment.question_index,
                )
            )
    return tuple(found)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/report.py tests/core/test_report.py
git commit -m "feat(core): list the words the recogniser did not catch"
```

---

### Task 5: Breakdowns, averages, and the answer-by-answer detail

**Files:**
- Modify: `src/opic/core/report.py`
- Test: `tests/core/test_report.py`

**Interfaces:**
- Consumes: `ITEMS_BY_ID` from `opic.core.survey`, `QUESTION_TYPE_LABELS_KO` (Task 1)
- Produces: `Report.by_type`, `Report.by_topic`, `Report.averages`, `Report.answers` populated

Rules:
- `averages` is the mean of the five shown metrics across scored answers; `None` when there are none.
- `answers` covers **every** question, in blueprint order. A question with no assessment is `state="not_scored"`, or `state="unreadable"` if its index is in `unreadable`. Those carry `metrics=None`, `transcript_text=""`, `scores=()`.
- `topic_label_ko` is `None` when `slot.topic_id` is `None` (self-intro and role-play carry no topic).

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_report.py`:

```python
def test_breakdowns_carry_korean_labels():
    report = report_of(3)
    assert report.by_type[0][1] == "묘사"
    assert report.by_topic[0][0] == "movies"
    assert report.by_topic[0][1] == "영화보기"


def test_averages_are_the_mean_of_the_shown_metrics():
    report = report_of(3)
    assert report.averages is not None
    assert report.averages.words_per_minute == 120.0
    assert not hasattr(report.averages, "type_token_ratio")


def test_every_question_appears_even_when_it_was_not_scored():
    level = {d: ActflLevel.IM2 for d in Dimension}
    assessments = [assessment(i, level) for i in range(2)]
    result = aggregate(blueprint_of(2), assessments)

    report = build_report(result, questions_of(3))

    assert [a.index for a in report.answers] == [0, 1, 2]
    assert report.answers[2].state == "not_scored"
    assert report.answers[2].metrics is None
    assert report.answers[2].scores == ()


def test_an_unreadable_answer_is_marked_apart_from_a_missing_one():
    level = {d: ActflLevel.IM2 for d in Dimension}
    assessments = [assessment(i, level) for i in range(2)]
    result = aggregate(blueprint_of(2), assessments)

    report = build_report(result, questions_of(3), unreadable=[2])

    assert report.answers[2].state == "unreadable"


def test_a_scored_answer_carries_its_comment_and_its_question():
    report = report_of(1)
    detail = report.answers[0]
    assert detail.state == "scored"
    assert detail.question_en == "Question 0"
    assert detail.qtype_label_ko == "묘사"
    assert detail.scores[0].comment_ko
```

`ITEMS_BY_ID["movies"].label_ko` is `"영화보기"` — no space. Verified against `src/opic/core/survey.py` on 2026-08-20; if it has moved, follow the source, not this line.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_report.py -k "breakdown or averages or question or unreadable" -v`
Expected: FAIL — `by_type` is `()`, `answers` is `()`

- [ ] **Step 3: Write minimal implementation**

In `src/opic/core/report.py`:

```python
from opic.core.survey import ITEMS_BY_ID


def _topic_label(topic_id: str | None) -> str | None:
    if topic_id is None:
        return None
    item = ITEMS_BY_ID.get(topic_id)
    return item.label_ko if item is not None else topic_id


def _averages(result: ExamResult) -> MetricSummary | None:
    if not result.assessments:
        return None
    count = len(result.assessments)
    take = lambda field: sum(  # noqa: E731
        getattr(a.metrics, field) for a in result.assessments
    ) / count
    return MetricSummary(
        duration_s=take("duration_s"),
        word_count=take("word_count"),
        words_per_minute=take("words_per_minute"),
        pause_ratio=take("pause_ratio"),
        mean_utterance_length=take("mean_utterance_length"),
    )


def _answers(
    result: ExamResult,
    questions: Sequence[Question],
    unreadable: Sequence[int],
) -> tuple[AnswerReport, ...]:
    judged = {a.question_index: a for a in result.assessments}
    broken = set(unreadable)
    reports = []
    for question in questions:
        index = question.slot.index
        assessment = judged.get(index)
        if assessment is None:
            reports.append(
                AnswerReport(
                    index=index,
                    question_en=question.text_en,
                    qtype_label_ko=QUESTION_TYPE_LABELS_KO[question.slot.qtype],
                    topic_label_ko=_topic_label(question.slot.topic_id),
                    state="unreadable" if index in broken else "not_scored",
                    transcript_text="",
                    metrics=None,
                    scores=(),
                )
            )
            continue
        m = assessment.metrics
        reports.append(
            AnswerReport(
                index=index,
                question_en=question.text_en,
                qtype_label_ko=QUESTION_TYPE_LABELS_KO[question.slot.qtype],
                topic_label_ko=_topic_label(question.slot.topic_id),
                state="scored",
                transcript_text=assessment.transcript.text,
                metrics=MetricSummary(
                    duration_s=m.duration_s,
                    word_count=m.word_count,
                    words_per_minute=m.words_per_minute,
                    pause_ratio=m.pause_ratio,
                    mean_utterance_length=m.mean_utterance_length,
                ),
                scores=tuple(
                    DimensionDetail(
                        dimension=score.dimension,
                        label_ko=DIMENSION_LABELS_KO[score.dimension],
                        level=score.level,
                        comment_ko=score.comment_ko,
                        evidence=score.evidence,
                    )
                    for score in assessment.dimension_scores
                ),
            )
        )
    return tuple(reports)
```

And in `build_report`, replace the empty placeholders:

```python
        by_type=tuple(
            (qtype, QUESTION_TYPE_LABELS_KO[qtype], level)
            for qtype, level in result.by_type
        ),
        by_topic=tuple(
            (topic_id, _topic_label(topic_id) or topic_id, level)
            for topic_id, level in result.by_topic
        ),
        averages=_averages(result),
        answers=_answers(result, questions, unreadable),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/core/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/report.py tests/core/test_report.py
git commit -m "feat(core): breakdowns, averages and the answer-by-answer detail"
```

---

### Task 6: `render_text` and the CLI

**Files:**
- Modify: `src/opic/core/report.py` (add `render_text`)
- Modify: `src/opic/cli.py:249-250`
- Test: `tests/core/test_report.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Report` (Task 3-5)
- Produces: `render_text(report: Report) -> str`

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_report.py`:

```python
from opic.core.report import render_text


def test_the_text_report_names_every_section_and_the_level():
    text = render_text(report_of(3))
    assert "최종 등급: IM2" in text
    assert "왜 이 등급인가" in text
    assert "유창성" in text
    assert "유형별" in text
    assert "답변별 상세" in text


def test_the_text_report_says_when_everything_was_understood():
    assert "또렷하게 인식되지 않은 단어는 없습니다" in render_text(report_of(3))


def test_the_text_report_explains_the_cap_when_it_fired():
    level = {d: ActflLevel.IH for d in Dimension}
    level[Dimension.GRAMMAR] = ActflLevel.NH
    assert "문법" in render_text(report_of(3, level))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_report.py -k text -v`
Expected: FAIL with `ImportError: cannot import name 'render_text'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/opic/core/report.py`:

```python
def render_text(report: Report) -> str:
    """The same report the browser shows, for a terminal."""
    lines: list[str] = []
    lines.append(f"최종 등급: {report.final_level.name}")
    lines.append(
        f"{report.expected_answers}개 중 {report.scored_answers}개의 답변으로 산출되었습니다."
    )
    lines.append("이 등급은 공식 점수가 아니며 실제 시험 결과를 예측하지 않습니다.")

    lines.append("")
    lines.append("왜 이 등급인가")
    if report.limiting is not None:
        lines.append(
            f"  최종 등급은 {report.limiting.label_ko}에 의해 한 단계 낮아졌습니다. "
            f"그 제한이 없었다면 {report.limiting.without_cap.name}입니다."
        )
    for dimension in report.dimensions:
        lines.append(
            f"  {dimension.label_ko} ({dimension.weight:.0%}): {dimension.level.name}"
        )
        for item in dimension.evidence:
            lines.append(f"    \"{item.quote}\" (질문 {item.answer_index + 1})")
            lines.append(f"      {item.issue_ko}")
            lines.append(f"      → {item.correction_en}")

    lines.append("")
    lines.append("또렷하게 인식되지 않은 단어")
    if not report.unclear:
        lines.append("  또렷하게 인식되지 않은 단어는 없습니다.")
    for word in report.unclear:
        lines.append(f"  {word.text} (질문 {word.answer_index + 1}): …{word.context}…")

    lines.append("")
    lines.append("유형별 · 주제별")
    for _, label_ko, level in report.by_type:
        lines.append(f"  {label_ko}: {level.name}")
    for _, label_ko, level in report.by_topic:
        lines.append(f"  {label_ko}: {level.name}")

    lines.append("")
    lines.append("답변별 상세")
    for answer in report.answers:
        if answer.state != "scored":
            note = "읽을 수 없는 파일" if answer.state == "unreadable" else "채점하지 못한 답변"
            lines.append(f"  질문 {answer.index + 1} — {note}")
            continue
        lines.append(f"  질문 {answer.index + 1} ({answer.qtype_label_ko})")
        lines.append(f"    {answer.question_en}")
        lines.append(f"    {answer.transcript_text}")
        if answer.metrics is not None and report.averages is not None:
            lines.append(
                f"    말하기 속도 {answer.metrics.words_per_minute:.0f}"
                f" (평균 {report.averages.words_per_minute:.0f}) · "
                f"침묵 비율 {answer.metrics.pause_ratio:.0%}"
                f" (평균 {report.averages.pause_ratio:.0%})"
            )
        for score in answer.scores:
            lines.append(f"    {score.label_ko}: {score.level.name} — {score.comment_ko}")

    return "\n".join(lines)
```

Then in `src/opic/cli.py`, replace lines 249-250:

```python
    from opic.core.report import build_report, render_text

    questions = [answers_on_disk.question_from_record(r) for r in state.questions]
    print()
    print(render_text(build_report(result, questions)))
    print(f"\n결과 파일: {args.session / 'result.json'}")
```

Check what `cli.py` already has in scope at that point — it has `result` and loads `state` at line 134. Reuse those names; do not re-load from disk.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_report.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/report.py src/opic/cli.py tests/core/test_report.py tests/test_cli.py
git commit -m "feat(cli): print the report, not just the level"
```

---

### Task 7: Serialise the report and serve it

**Files:**
- Modify: `src/opic/session/assessments.py` (add `report_json` after `result_json`, which ends line 113)
- Modify: `src/opic/web/app.py` (add a route after `result`, which ends line 349)
- Test: `tests/web/test_report_route.py` (create)

**Interfaces:**
- Consumes: `build_report` (Task 3-5), `read_all_answers`, `aggregate_available`, `question_from_record` (all existing in `assessments.py`), `store.result_path`, `load_or_404`
- Produces: `report_json(report: Report) -> dict`; `GET /api/sessions/{id}/report`

`aggregate_available`, not `aggregate` — `aggregate` requires the assessments to match the blueprint exactly and raises on a failed answer (`scoring.py:148-152`).

`read_answer` raises `JSONDecodeError` on a corrupt file, which today would 500 a completed exam. The route reads answers one by one and collects the broken indices instead.

- [ ] **Step 1: Write the failing test**

Create `tests/web/test_report_route.py`. Follow the existing `tests/web/conftest.py` fixtures — read it first and reuse the same client/session setup as `tests/web/test_answer_routes.py`.

```python
from __future__ import annotations

import json


def test_the_report_is_a_404_until_the_exam_is_scored(client, session_id):
    assert client.get(f"/api/sessions/{session_id}/report").status_code == 404


def test_the_report_carries_the_sections_the_screen_needs(client, scored_session):
    payload = client.get(f"/api/sessions/{scored_session}/report").json()

    assert payload["final_level"]
    assert payload["expected_answers"] >= payload["scored_answers"]
    assert len(payload["dimensions"]) == 5
    assert payload["dimensions"][0]["label_ko"] == "유창성"
    assert "unclear" in payload
    assert "answers" in payload


def test_a_corrupt_answer_file_does_not_cost_the_whole_report(
    client, scored_session, sessions_root
):
    broken = sessions_root / scored_session / "answer-00.json"
    broken.write_text("{ not json", encoding="utf-8")

    payload = client.get(f"/api/sessions/{scored_session}/report").json()

    assert payload["answers"][0]["state"] == "unreadable"
    assert payload["scored_answers"] >= 1


def test_the_raw_result_route_is_unchanged(client, scored_session):
    payload = client.get(f"/api/sessions/{scored_session}/result").json()
    assert set(payload) >= {
        "final_level",
        "scored_answers",
        "expected_answers",
        "dimensions",
        "by_type",
        "by_topic",
        "pronunciation",
        "answers",
    }
```

If `scored_session` / `sessions_root` fixtures do not exist in `tests/web/conftest.py`, add them there, building on whatever `test_answer_routes.py::test_a_whole_exam_ends_with_a_level` already does to drive a session to a written `result.json`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/web/test_report_route.py -v`
Expected: FAIL with 404 on a scored session (route does not exist)

- [ ] **Step 3: Write minimal implementation**

In `src/opic/session/assessments.py`:

```python
from opic.core.report import Report


def report_json(report: Report) -> dict:
    return {
        "final_level": report.final_level.name,
        "scored_answers": report.scored_answers,
        "expected_answers": report.expected_answers,
        "limiting": (
            {
                "dimension": report.limiting.dimension.value,
                "label_ko": report.limiting.label_ko,
                "level": report.limiting.level.name,
                "without_cap": report.limiting.without_cap.name,
            }
            if report.limiting is not None
            else None
        ),
        "dimensions": [
            {
                "dimension": d.dimension.value,
                "label_ko": d.label_ko,
                "weight": d.weight,
                "level": d.level.name,
                "evidence": [
                    {
                        "quote": e.quote,
                        "issue_ko": e.issue_ko,
                        "correction_en": e.correction_en,
                        "answer_index": e.answer_index,
                    }
                    for e in d.evidence
                ],
            }
            for d in report.dimensions
        ],
        "unclear": [
            {
                "text": w.text,
                "probability": w.probability,
                "context": w.context,
                "answer_index": w.answer_index,
            }
            for w in report.unclear
        ],
        "by_type": [
            {"id": t.value, "label_ko": label, "level": level.name}
            for t, label, level in report.by_type
        ],
        "by_topic": [
            {"id": topic, "label_ko": label, "level": level.name}
            for topic, label, level in report.by_topic
        ],
        "averages": _metrics_json(report.averages),
        "answers": [
            {
                "index": a.index,
                "question_en": a.question_en,
                "qtype_label_ko": a.qtype_label_ko,
                "topic_label_ko": a.topic_label_ko,
                "state": a.state,
                "transcript_text": a.transcript_text,
                "metrics": _metrics_json(a.metrics),
                "scores": [
                    {
                        "dimension": s.dimension.value,
                        "label_ko": s.label_ko,
                        "level": s.level.name,
                        "comment_ko": s.comment_ko,
                        "evidence": [
                            {
                                "quote": e.quote,
                                "issue_ko": e.issue_ko,
                                "correction_en": e.correction_en,
                            }
                            for e in s.evidence
                        ],
                    }
                    for s in a.scores
                ],
            }
            for a in report.answers
        ],
    }


def _metrics_json(metrics) -> dict | None:
    if metrics is None:
        return None
    return {
        "duration_s": metrics.duration_s,
        "word_count": metrics.word_count,
        "words_per_minute": metrics.words_per_minute,
        "pause_ratio": metrics.pause_ratio,
        "mean_utterance_length": metrics.mean_utterance_length,
    }


def read_answers_tolerantly(
    root: Path, session_id: str, state: SessionState
) -> tuple[tuple[AnswerAssessment, ...], tuple[int, ...]]:
    """Every answer that could be read, and the indices of the ones that could not.

    A single corrupt `answer-NN.json` must not cost the candidate the other
    fourteen, so this reports the damage instead of raising.
    """
    scored = set(state.scored_indices())
    found = []
    broken = []
    for record in state.questions:
        if record.index not in scored:
            continue
        try:
            found.append(read_answer(root, session_id, record.index))
        except (OSError, ValueError):
            broken.append(record.index)
    return tuple(found), tuple(broken)
```

`json.JSONDecodeError` subclasses `ValueError`, so the `except` covers it.

In `src/opic/web/app.py`, after the `result` route:

```python
    @app.get("/api/sessions/{session_id}/report")
    def report(session_id: str):
        state = load_or_404(session_id)
        if not store.result_path(root, session_id).exists():
            raise HTTPException(status_code=404, detail="not scored yet")
        judged, broken = answers_on_disk.read_answers_tolerantly(root, session_id, state)
        if not judged:
            raise HTTPException(status_code=404, detail="not scored yet")
        exam = answers_on_disk.aggregate_available(state.questions, judged)
        questions = [answers_on_disk.question_from_record(r) for r in state.questions]
        built = build_report(exam, questions, unreadable=broken)
        return JSONResponse(content=answers_on_disk.report_json(built))
```

Add `from opic.core.report import build_report` to the imports in `app.py`. Check how `assessments` is already imported there (the worker imports it as `answers_on_disk`); match whatever name `app.py` uses, or add the import.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/web/ -v`
Expected: PASS, including `test_answer_routes.py` unedited.

- [ ] **Step 5: Commit**

```bash
git add src/opic/session/assessments.py src/opic/web/app.py tests/web/
git commit -m "feat(web): serve the report, and survive one unreadable answer"
```

---

### Task 8: The screen

**Files:**
- Modify: `src/opic/web/static/steps/done.js` (rewrite)
- Modify: `src/opic/web/static/style.css` (add the classes the new markup needs)

**Interfaces:**
- Consumes: `GET /api/sessions/{id}/report` (Task 7), `GET /api/sessions/{id}/result` (unchanged, for the raw `<details>`)
- Produces: nothing other modules import

`done.js` decides nothing: it iterates the payload and appends elements. Every string it prints comes from the API, except the fixed section headings and the caveat.

The retry-on-failed-fetch path at `done.js:12-27` must survive the rewrite — a blank page after a 40-minute exam is the worst possible ending, and that is the code that prevents it.

- [ ] **Step 1: Write the sections**

Rewrite `render`/`load` so the screen shows, in order:

1. `최종 등급: {final_level}`, the `N개 중 M개` line (class `issues` when `scored < expected`), and the caveat — **with the pronunciation sentence removed**, since the words section now delivers it: `"이 등급은 공식 점수가 아니며 실제 시험 결과를 예측하지 않습니다."`
2. `왜 이 등급인가` — the `limiting` line when present, then each dimension: `{label_ko} ({weight as %}): {level}`, and under it each evidence item as quote / `issue_ko` / `→ correction_en` / `질문 {answer_index + 1}`.
3. `또렷하게 인식되지 않은 단어` — one line per unclear word: the word, `질문 {answer_index + 1}`, and `…{context}…`. When `unclear` is empty, the single line `또렷하게 인식되지 않은 단어는 없습니다.`
4. `유형별 · 주제별` — two lists from `by_type` and `by_topic`. Skip a list entirely when its array is empty.
5. `답변별 상세` — a `<details>` per answer, summary `질문 {index + 1} ({qtype_label_ko})`. Inside: the question, the transcript, the metrics against `averages`, and each score with its `comment_ko` and evidence. For `state !== "scored"`, the summary carries `채점하지 못한 답변` (or `읽을 수 없는 파일`) and there is no body.
6. The existing `전체 결과 (JSON)` `<details>` against `/result`, and the `새 시험 시작` button, both unchanged.

- [ ] **Step 2: Check it against the real exam**

The acceptance run of 2026-08-20 left a fully graded session on disk. Start the server and open the report for it:

```bash
uv run python -m opic.cli --serve
```

Then open `http://localhost:8000`, and in the console:

```js
localStorage.setItem("opic.session", "<session id from data/sessions/>"); location.reload();
```

Expected: the report renders with real Korean comments and real quotes. **Read it.** Anything unreadable, mis-ordered, or overflowing is a finding for this task, not a later one.

- [ ] **Step 3: Commit**

```bash
git add src/opic/web/static/steps/done.js src/opic/web/static/style.css
git commit -m "feat(web): the result screen becomes a report"
```

---

### Task 9: Pin it to real model output

**Files:**
- Create: `evidence/sample-result.json`, `evidence/sample-answers/answer-NN.json`
- Test: `tests/core/test_report_real_data.py` (create)

**Interfaces:**
- Consumes: `build_report`, `render_text`, `_answer_from_json` (existing, `assessments.py`)

The fixtures come from the acceptance run of 2026-08-20 — real qwen3:14b judgements over real speech. Same reasoning as `evidence/sample-transcript.json`: the tests run against what the model actually emits, not against invented data. It carries a case a hand-written fixture would not have had — the run's first answer returned **two** evidence items for one dimension, though the prompt asks for at most one.

- [ ] **Step 1: Copy the fixtures**

```bash
mkdir -p evidence/sample-answers
cp data/sessions/<run-id>/result.json evidence/sample-result.json
cp data/sessions/<run-id>/answer-*.json evidence/sample-answers/
```

Add a `_note` key to `evidence/sample-result.json` in the style of `sample-transcript.json`, saying where it came from and on what date.

- [ ] **Step 2: Write the failing test**

Create `tests/core/test_report_real_data.py`:

```python
from __future__ import annotations

import json
import pathlib

from opic.core.report import build_report, render_text
from opic.session.assessments import _answer_from_json, aggregate_available

EVIDENCE = pathlib.Path(__file__).resolve().parents[2] / "evidence"


def load_assessments():
    files = sorted((EVIDENCE / "sample-answers").glob("answer-*.json"))
    return [_answer_from_json(json.loads(f.read_text(encoding="utf-8"))) for f in files]


def test_a_real_exam_produces_a_report_with_evidence_in_it():
    assessments = load_assessments()
    questions = [a.question for a in assessments]
    result = aggregate_available_from(questions, assessments)

    report = build_report(result, questions)

    assert report.scored_answers == len(assessments)
    quoted = [e for d in report.dimensions for e in d.evidence]
    assert quoted, "the real run produced evidence; the report dropped it"
    assert any(len(d.evidence) > 1 for d in report.dimensions)


def test_the_real_report_renders_as_text_without_raising():
    assessments = load_assessments()
    questions = [a.question for a in assessments]
    text = render_text(build_report(aggregate_available_from(questions, assessments), questions))
    assert "최종 등급" in text
```

`aggregate_available` takes `QuestionRecord`s, not `Question`s. Write a small local `aggregate_available_from(questions, assessments)` in this test file that calls `opic.core.scoring.aggregate` with `tuple(q.slot for q in questions)` — the fixtures are a complete run, so plain `aggregate` applies.

- [ ] **Step 3: Run test to verify it fails, then passes**

Run: `uv run --extra dev pytest tests/core/test_report_real_data.py -v`
Expected: FAIL before the fixtures are copied, PASS after.

- [ ] **Step 4: Run the whole suite**

Run: `uv run --extra dev pytest`
Expected: PASS, everything.

- [ ] **Step 5: Commit**

```bash
git add evidence/ tests/core/test_report_real_data.py
git commit -m "test: pin the report to a real graded exam"
```

---

## Self-review notes

Spec coverage checked section by section:

- §5.1 model → Tasks 3, 4, 5. §5.2 serialisation → Task 7. §5.3 route → Task 7.
- §6 the cap → Task 2. §7.1-7.5 sections → Tasks 3-5 (model), 6 (text), 8 (screen).
- §7.6 type labels → Task 1. §7.7 metrics → Task 5.
- §8 `done.js` and CLI → Tasks 6 and 8. §9 failures → Tasks 5 and 7. §10 verification → every task, plus 9.

Two deviations from the spec, both deliberate and noted at their task:

1. `QUESTION_TYPE_LABELS_KO` goes in `questions.py`, not `rubric.py`: `questions.py` already imports `rubric.py`, so the spec's placement would be a circular import (Task 1).
2. The `/report` route reads answers through a new `read_answers_tolerantly` rather than `read_all_answers`, because the existing function propagates a corrupt file's `JSONDecodeError` and the spec requires surviving it (Task 7).
