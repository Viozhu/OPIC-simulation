# Phase 2, Plan A — Core Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the four core types that promise more than they deliver, and
recompute the pause and utterance metrics from data Whisper actually provides.

**Architecture:** All work stays inside `src/opic/core/`, which keeps importing
nothing from FastAPI, Ollama, Whisper, Piper or sqlite3. Transcript data moves
into its own module so the three ports of Plan B can import it without dragging
in the metrics code. No model is downloaded or called by any task here.

**Tech Stack:** Python 3.13, uv, pytest. No runtime dependencies in `core/`.

**Spec:** `docs/superpowers/specs/2026-08-19-phase-2-adapters-design.md` (sections 4 and 5)

## Global Constraints

- Python 3.13. Project managed with `uv`. Run tests with `uv run --extra dev pytest`.
- `src/opic/core/` must not import `fastapi`, `httpx`, `requests`, `ollama`,
  `faster_whisper`, `piper`, or `sqlite3`. `tests/test_core_purity.py` enforces this.
- Import style: every module starts with `from __future__ import annotations`.
- All dataclasses in `core/` are `@dataclass(frozen=True, slots=True)`. Collections
  they hold are tuples, never lists — this now includes `ExamResult.dimension_levels`.
- ACTFL scale, in this exact order: NL, NM, NH, IL, IM1, IM2, IM3, IH, AL.
- `PAUSE_THRESHOLD_S` is 0.5 seconds and governs both span merging and pause detection.
- Korean user-facing strings end in `_ko`; English exam content ends in `_en`.
- Determinism: same input must always produce the same result. Never iterate a set
  or an unordered dict where output order depends on it.
- Commit after every task. The full suite must be green before each commit.

## Files

| File | Responsibility | Task |
|---|---|---|
| `src/opic/core/transcript.py` | NEW. `Word`, `Span`, `Transcript` — what an STT adapter returns | 1 |
| `src/opic/core/metrics.py` | MODIFY. Pauses and utterances from speech spans, not word gaps | 2 |
| `src/opic/core/survey.py` | MODIFY. `RecentCourse` and its validation rule | 3 |
| `src/opic/core/questions.py` | MODIFY. `Question` — a slot plus its English text | 4 |
| `src/opic/core/scoring.py` | MODIFY. Blueprint-aware aggregation, immutable levels | 5 |
| `tests/test_core_purity.py` | MODIFY. Guard the new module too | 6 |

---

### Task 1: Transcript types

`Word` moves out of `metrics.py`. It describes transcription output, not a metric,
and leaving it there would force `core/transcript.py` to import `metrics.py` while
`metrics.py` imports `Transcript` — a cycle.

**Files:**
- Create: `src/opic/core/transcript.py`
- Modify: `src/opic/core/metrics.py` (remove the `Word` dataclass, import it instead)
- Modify: `tests/core/test_metrics.py` (import `Word` from its new home)
- Test: `tests/core/test_transcript.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Word(text: str, start: float, end: float, probability: float)` — unchanged shape.
  - `Span(start: float, end: float)` with a `duration` property.
  - `Transcript(text: str, words: tuple[Word, ...], speech_spans: tuple[Span, ...],
    duration_s: float)`, raising `ValueError` on a non-positive `duration_s`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_transcript.py`:

```python
from __future__ import annotations

import pytest

from opic.core.transcript import Span, Transcript, Word


def test_span_reports_its_duration():
    assert Span(1.5, 4.0).duration == pytest.approx(2.5)


def test_a_transcript_holds_words_and_speech_spans():
    words = (Word("hello", 0.0, 0.5, 0.9),)
    spans = (Span(0.0, 0.5),)
    t = Transcript(text="hello", words=words, speech_spans=spans, duration_s=3.0)
    assert t.words == words
    assert t.speech_spans == spans
    assert t.duration_s == 3.0


@pytest.mark.parametrize("duration", [0.0, -1.0])
def test_a_non_positive_duration_is_refused(duration):
    with pytest.raises(ValueError):
        Transcript(text="", words=(), speech_spans=(), duration_s=duration)


def test_a_transcript_is_frozen():
    t = Transcript(text="hi", words=(), speech_spans=(), duration_s=1.0)
    with pytest.raises(Exception):
        t.text = "bye"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_transcript.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.core.transcript'`.

- [ ] **Step 3: Write the implementation**

Create `src/opic/core/transcript.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Word:
    """One transcribed word with its timing and the model's confidence in it."""

    text: str
    start: float
    end: float
    probability: float


@dataclass(frozen=True, slots=True)
class Span:
    """A stretch of detected speech, in seconds from the start of the audio."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class Transcript:
    """What a speech-to-text adapter hands back.

    `speech_spans` comes from voice activity detection, not from word timings.
    Whisper aligns words continuously, so the gaps between them do not show
    where the speaker actually stopped.
    """

    text: str
    words: tuple[Word, ...]
    speech_spans: tuple[Span, ...]
    duration_s: float

    def __post_init__(self) -> None:
        if self.duration_s <= 0:
            raise ValueError(f"duration_s must be positive, got {self.duration_s!r}")
```

- [ ] **Step 4: Move `Word` out of `metrics.py`**

In `src/opic/core/metrics.py`, delete the `Word` dataclass (the `@dataclass` block
declaring `text`, `start`, `end`, `probability`) and add this import below the
existing `from dataclasses import dataclass` line:

```python
from opic.core.transcript import Word
```

In `tests/core/test_metrics.py`, change the import line
`from opic.core.metrics import Word, compute_metrics` to:

```python
from opic.core.metrics import compute_metrics
from opic.core.transcript import Word
```

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS. `Word` is re-exported through `metrics` by the import, so every
existing test keeps working unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/opic/core/transcript.py src/opic/core/metrics.py tests/core/test_transcript.py tests/core/test_metrics.py
git commit -m "refactor(core): move transcript types into their own module"
```

---

### Task 2: Metrics from speech spans

The spike measured `pause_ratio` 0.011 and `mean_utterance_length` 75 over 90
seconds of real speech, because Whisper's word timings almost never leave a gap
wider than the threshold. Both now come from voice-activity spans instead.

**Files:**
- Modify: `src/opic/core/metrics.py`
- Modify: `tests/core/test_metrics.py` (replaced wholesale)
- Modify: `tests/core/test_core_end_to_end.py` (build a `Transcript`)

**Interfaces:**
- Consumes: `Word`, `Span`, `Transcript` from `opic.core.transcript`.
- Produces:
  - `merge_spans(spans: Sequence[Span], threshold: float = PAUSE_THRESHOLD_S) -> tuple[Span, ...]`
  - `compute_metrics(transcript: Transcript) -> AnswerMetrics` — note the single
    argument; the old `(words, duration_s)` signature is gone.
  - `AnswerMetrics` keeps all ten fields it has today.

Definitions, all deterministic:
- Spans separated by less than `PAUSE_THRESHOLD_S` merge. Merged spans are utterances.
- Gaps between utterances are pauses. Silence before the first utterance and after
  the last does not count — that is recording margin, not hesitation.
- `pause_ratio` = paused time / (last utterance end − first utterance start).
- `mean_utterance_length` = word count / utterance count.
- With no spans at all: `pause_ratio` 0.0 and the whole answer counts as one
  utterance, so `mean_utterance_length` equals the word count.

`filler_count` and `filler_rate` stay untouched. Plan B decides whether they
survive, after testing whether `initial_prompt` recovers disfluencies.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/core/test_metrics.py`:

```python
from __future__ import annotations

import pytest

from opic.core.metrics import compute_metrics, merge_spans
from opic.core.transcript import Span, Transcript, Word


def make(
    texts: list[str],
    *,
    spans: list[tuple[float, float]] | None = None,
    step: float = 0.5,
    probability: float = 0.9,
    duration_s: float = 10.0,
    probabilities: list[float] | None = None,
) -> Transcript:
    words = tuple(
        Word(
            text=text,
            start=i * step,
            end=i * step + step / 2,
            probability=probabilities[i] if probabilities else probability,
        )
        for i, text in enumerate(texts)
    )
    if spans is None:
        spans = [(0.0, max(step, len(texts) * step))]
    return Transcript(
        text=" ".join(texts),
        words=words,
        speech_spans=tuple(Span(a, b) for a, b in spans),
        duration_s=duration_s,
    )


def test_merge_spans_joins_spans_closer_than_the_threshold():
    merged = merge_spans((Span(0.0, 1.0), Span(1.2, 2.0)))
    assert merged == (Span(0.0, 2.0),)


def test_merge_spans_keeps_spans_further_apart_than_the_threshold():
    spans = (Span(0.0, 1.0), Span(4.0, 5.0))
    assert merge_spans(spans) == spans


def test_merge_spans_handles_an_empty_input():
    assert merge_spans(()) == ()


def test_empty_speech_yields_zeroed_metrics():
    t = Transcript(text="", words=(), speech_spans=(), duration_s=10.0)
    m = compute_metrics(t)
    assert m.word_count == 0
    assert m.words_per_minute == 0.0
    assert m.type_token_ratio == 0.0
    assert m.pause_ratio == 0.0
    assert m.mean_utterance_length == 0.0


def test_words_per_minute_counts_words_over_the_recording_length():
    m = compute_metrics(make(["one"] * 30, duration_s=60.0))
    assert m.words_per_minute == pytest.approx(30.0)


def test_pause_ratio_measures_silence_between_utterances():
    m = compute_metrics(make(["a", "b"], spans=[(0.0, 1.0), (4.0, 5.0)], duration_s=10.0))
    assert m.pause_ratio == pytest.approx(0.6)


def test_leading_and_trailing_silence_is_not_a_pause():
    early = compute_metrics(make(["a", "b"], spans=[(0.0, 1.0), (4.0, 5.0)], duration_s=10.0))
    late = compute_metrics(make(["a", "b"], spans=[(2.0, 3.0), (6.0, 7.0)], duration_s=20.0))
    assert late.pause_ratio == pytest.approx(early.pause_ratio)


def test_a_short_gap_is_not_a_pause():
    m = compute_metrics(make(["a", "b"], spans=[(0.0, 1.0), (1.2, 2.0)], duration_s=10.0))
    assert m.pause_ratio == 0.0


def test_mean_utterance_length_divides_words_by_utterances():
    m = compute_metrics(make(["a", "b", "c"], spans=[(0.0, 1.0), (4.0, 5.0)], duration_s=10.0))
    assert m.mean_utterance_length == pytest.approx(1.5)


def test_without_speech_spans_the_answer_counts_as_one_utterance():
    t = Transcript(
        text="a b c",
        words=tuple(Word(x, 0.0, 0.1, 0.9) for x in ("a", "b", "c")),
        speech_spans=(),
        duration_s=10.0,
    )
    m = compute_metrics(t)
    assert m.mean_utterance_length == pytest.approx(3.0)
    assert m.pause_ratio == 0.0


def test_fillers_are_counted_case_insensitively_and_without_punctuation():
    m = compute_metrics(make(["Um,", "I", "uh", "think", "so"]))
    assert m.filler_count == 2
    assert m.filler_rate == pytest.approx(2 / 5)


def test_common_words_that_are_not_hesitations_are_not_fillers():
    m = compute_metrics(make(["I", "like", "it", "so", "well"]))
    assert m.filler_count == 0


def test_type_token_ratio_measures_lexical_variety():
    m = compute_metrics(make(["cat", "cat", "dog", "bird"]))
    assert m.type_token_ratio == pytest.approx(0.75)


def test_confidence_metrics_flag_doubtful_words():
    m = compute_metrics(make(["clear", "mumbled"], probabilities=[0.95, 0.25]))
    assert m.mean_confidence == pytest.approx(0.6)
    assert m.low_confidence_rate == pytest.approx(0.5)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/core/test_metrics.py -v`
Expected: FAIL with `ImportError: cannot import name 'merge_spans'`.

- [ ] **Step 3: Write the implementation**

In `src/opic/core/metrics.py`, replace everything from the `def compute_metrics`
line to the end of the file with:

```python
def merge_spans(
    spans: Sequence[Span],
    threshold: float = PAUSE_THRESHOLD_S,
) -> tuple[Span, ...]:
    """Join speech spans separated by less than the pause threshold.

    Voice activity detection splits on breath and micro-gaps. Merging first means
    an utterance is what a listener would call one, not what the detector emitted.
    """
    if not spans:
        return ()

    ordered = sorted(spans, key=lambda span: span.start)
    merged = [ordered[0]]
    for span in ordered[1:]:
        last = merged[-1]
        if span.start - last.end < threshold:
            merged[-1] = Span(last.start, max(last.end, span.end))
        else:
            merged.append(span)
    return tuple(merged)


def compute_metrics(transcript: Transcript) -> AnswerMetrics:
    """Derive the objective half of the score.

    Everything here is arithmetic, which is exactly why it does not go to the
    model: a local LLM will happily invent a words-per-minute figure.

    Pauses come from voice activity spans rather than from gaps between word
    timings. Whisper aligns words continuously, so those gaps stay near zero
    however long the speaker actually hesitated.
    """
    words = transcript.words
    duration_s = transcript.duration_s
    count = len(words)

    if count == 0:
        return AnswerMetrics(
            duration_s=duration_s,
            word_count=0,
            words_per_minute=0.0,
            pause_ratio=0.0,
            filler_count=0,
            filler_rate=0.0,
            type_token_ratio=0.0,
            mean_utterance_length=0.0,
            mean_confidence=0.0,
            low_confidence_rate=0.0,
        )

    utterances = merge_spans(transcript.speech_spans)
    if utterances:
        window = utterances[-1].end - utterances[0].start
        paused = sum(
            later.start - earlier.end
            for earlier, later in zip(utterances, utterances[1:], strict=False)
        )
        pause_ratio = min(1.0, paused / window) if window > 0 else 0.0
        mean_utterance_length = count / len(utterances)
    else:
        pause_ratio = 0.0
        mean_utterance_length = float(count)

    tokens = [_normalise(word.text) for word in words]
    spoken = [token for token in tokens if token]
    fillers = sum(1 for token in spoken if token in FILLERS)
    confidences = [word.probability for word in words]
    doubtful = sum(1 for value in confidences if value < LOW_CONFIDENCE_THRESHOLD)

    return AnswerMetrics(
        duration_s=duration_s,
        word_count=count,
        words_per_minute=count / duration_s * 60.0,
        pause_ratio=pause_ratio,
        filler_count=fillers,
        filler_rate=fillers / count,
        type_token_ratio=len(set(spoken)) / len(spoken) if spoken else 0.0,
        mean_utterance_length=mean_utterance_length,
        mean_confidence=sum(confidences) / count,
        low_confidence_rate=doubtful / count,
    )
```

Update the import line at the top of the file so it reads:

```python
from opic.core.transcript import Span, Transcript, Word
```

- [ ] **Step 4: Fix the end-to-end test**

In `tests/core/test_core_end_to_end.py`, replace the import line
`from opic.core.metrics import Word, compute_metrics` with:

```python
from opic.core.metrics import compute_metrics
from opic.core.transcript import Span, Transcript, Word
```

and replace the two statements building `words` and `metrics` with:

```python
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
```

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opic/core/metrics.py tests/core/test_metrics.py tests/core/test_core_end_to_end.py
git commit -m "fix(core): derive pauses and utterances from speech spans"
```

---

### Task 3: Recent course in the Background Survey

Part 2 of the survey asks a non-student which course they last took. The fourth
option on the real screen is really a recency answer, so one field covers it.

**Files:**
- Modify: `src/opic/core/survey.py`
- Modify: `tests/core/test_survey.py`
- Modify: `tests/core/test_questions.py` (its `SurveyAnswers` fixtures)
- Modify: `tests/core/test_core_end_to_end.py` (same reason)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `RecentCourse` — DEGREE, PROFESSIONAL, LANGUAGE, OVER_FIVE_YEARS_AGO.
  - `RECENT_COURSE_LABELS_KO: dict[RecentCourse, str]`.
  - `SurveyAnswers.recent_course: RecentCourse | None = None` — a new field with a
    default, appended last so existing keyword construction keeps working.
  - `SurveyError.MISSING_COURSE` and `SurveyError.UNEXPECTED_COURSE`.

The spec names only `MISSING_COURSE`. Two members are used instead of one, because
a student who reports a course is not missing anything — reusing one name for both
directions would make the error's own name a lie.

- [ ] **Step 1: Write the failing test**

In `tests/core/test_survey.py`, extend the existing import from `opic.core.survey`
with `RECENT_COURSE_LABELS_KO` and `RecentCourse`, then change the `answers_with`
helper to supply the new field:

```python
def answers_with(
    selection: tuple[str, ...],
    *,
    is_student: bool = False,
    recent_course: RecentCourse | None = RecentCourse.LANGUAGE,
) -> SurveyAnswers:
    return SurveyAnswers(
        occupation=Occupation.BUSINESS,
        is_student=is_student,
        housing=Housing.WITH_FAMILY,
        selected_item_ids=selection,
        recent_course=recent_course,
    )
```

Then append these tests:

```python
def test_every_recent_course_option_has_a_korean_label():
    assert set(RECENT_COURSE_LABELS_KO) == set(RecentCourse)
    assert all(label.strip() for label in RECENT_COURSE_LABELS_KO.values())


def test_a_non_student_must_report_a_recent_course():
    issues = validate_survey(answers_with(valid_selection(), recent_course=None))
    assert SurveyError.MISSING_COURSE in {issue.error for issue in issues}


def test_a_student_must_not_report_a_recent_course():
    issues = validate_survey(
        answers_with(
            valid_selection(),
            is_student=True,
            recent_course=RecentCourse.DEGREE,
        )
    )
    assert SurveyError.UNEXPECTED_COURSE in {issue.error for issue in issues}


def test_a_student_without_a_recent_course_is_valid():
    assert validate_survey(
        answers_with(valid_selection(), is_student=True, recent_course=None)
    ) == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/core/test_survey.py -v`
Expected: FAIL with `ImportError: cannot import name 'RecentCourse'`.

- [ ] **Step 3: Write the implementation**

In `src/opic/core/survey.py`, add after the `Housing` enum:

```python
class RecentCourse(Enum):
    """Part 2 of the survey: the last course a non-student took."""

    DEGREE = "degree"
    PROFESSIONAL = "professional"
    LANGUAGE = "language"
    OVER_FIVE_YEARS_AGO = "over_5y"


RECENT_COURSE_LABELS_KO: dict[RecentCourse, str] = {
    RecentCourse.DEGREE: "학위 과정 수업",
    RecentCourse.PROFESSIONAL: "전문 기술 향상을 위한 평생 학습",
    RecentCourse.LANGUAGE: "어학수업",
    RecentCourse.OVER_FIVE_YEARS_AGO: "수강 후 5년 이상 지남",
}
```

Add the field to `SurveyAnswers`, last, with its default:

```python
@dataclass(frozen=True, slots=True)
class SurveyAnswers:
    occupation: Occupation
    is_student: bool
    housing: Housing
    selected_item_ids: tuple[str, ...]
    recent_course: RecentCourse | None = None
```

Add two members to `SurveyError`, after `GROUP_MINIMUM`:

```python
    MISSING_COURSE = "missing_course"
    UNEXPECTED_COURSE = "unexpected_course"
```

In `validate_survey`, insert this immediately before the final `return tuple(issues)`:

```python
    if answers.is_student and answers.recent_course is not None:
        issues.append(
            ValidationIssue(
                SurveyError.UNEXPECTED_COURSE,
                answers.recent_course.value,
            )
        )
    elif not answers.is_student and answers.recent_course is None:
        issues.append(ValidationIssue(SurveyError.MISSING_COURSE, "not a student"))
```

- [ ] **Step 4: Fix the other two fixtures**

In `tests/core/test_questions.py`, extend the import from `opic.core.survey` with
`RecentCourse`, then add `recent_course=RecentCourse.LANGUAGE,` as the last
argument of BOTH `SurveyAnswers(...)` constructions — the one inside
`valid_answers()` and the one inside `test_a_lopsided_selection_still_reaches_every_group`.

In `tests/core/test_core_end_to_end.py`, do the same: extend the import with
`RecentCourse` and add `recent_course=RecentCourse.LANGUAGE,` to the
`SurveyAnswers(...)` construction.

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opic/core/survey.py tests/core/test_survey.py tests/core/test_questions.py tests/core/test_core_end_to_end.py
git commit -m "feat(core): record the survey's recent-course answer"
```

---

### Task 4: The Question type

The question's English text is persisted and quoted in the report, which makes it
a domain type. Defining it in the Ollama adapter would invert the dependency and
leave `core/` importing from infrastructure to read its own data.

**Files:**
- Modify: `src/opic/core/questions.py`
- Modify: `tests/core/test_questions.py`

**Interfaces:**
- Consumes: `QuestionSlot` from the same module.
- Produces: `Question(slot: QuestionSlot, text_en: str)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_questions.py` (extend the existing import from
`opic.core.questions` with `Question`):

```python
def test_a_question_pairs_a_slot_with_its_english_text():
    blueprint = build_blueprint(valid_answers(), self_assess_level=4, seed=7)
    q = Question(slot=blueprint[0], text_en="Tell me a little about yourself.")
    assert q.slot.qtype is QuestionType.SELF_INTRO
    assert q.text_en.endswith(".")


def test_a_question_is_frozen():
    blueprint = build_blueprint(valid_answers(), self_assess_level=4, seed=7)
    q = Question(slot=blueprint[0], text_en="Tell me a little about yourself.")
    with pytest.raises(Exception):
        q.text_en = "something else"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_questions.py -v`
Expected: FAIL with `ImportError: cannot import name 'Question'`.

- [ ] **Step 3: Write the implementation**

In `src/opic/core/questions.py`, add immediately after the `QuestionSlot`
dataclass:

```python
@dataclass(frozen=True, slots=True)
class Question:
    """A slot once its English text exists.

    The blueprint says what to ask about; this says what was actually asked. The
    report quotes it, so it is domain data and belongs here rather than in
    whichever adapter happened to generate the wording.
    """

    slot: QuestionSlot
    text_en: str
```

- [ ] **Step 4: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/questions.py tests/core/test_questions.py
git commit -m "feat(core): add the Question type"
```

---

### Task 5: Blueprint-aware aggregation

Three defects close together: the result's dimension map is a mutable `dict` on a
frozen dataclass, the report cannot break performance down by topic or question
type, and the advanced combo has no effect on the score at all.

**Files:**
- Modify: `src/opic/core/scoring.py`
- Modify: `tests/core/test_scoring.py`
- Modify: `tests/core/test_core_end_to_end.py`

**Interfaces:**
- Consumes: `QuestionSlot`, `QuestionType` from `opic.core.questions`;
  `ActflLevel`, `Dimension`, `DIMENSION_WEIGHTS` from `opic.core.rubric`.
- Produces:
  - `aggregate(blueprint: Sequence[QuestionSlot], assessments: Sequence[AnswerAssessment]) -> ExamResult`
  - `ExamResult(final_level, dimension_levels: tuple[tuple[Dimension, ActflLevel], ...],
    by_type: tuple[tuple[QuestionType, ActflLevel], ...],
    by_topic: tuple[tuple[str, ActflLevel], ...], pronunciation, assessments)`
    with a method `level_for(dimension) -> ActflLevel`.
  - `dimension_level(assessments, dimension) -> ActflLevel` — unchanged behaviour.

The aggregation rule, in order:
1. Per dimension, the median across answers; even counts take the lower middle.
2. The weighted mean of those ranks, floored.
3. If any dimension sits `WEAK_DIMENSION_GAP` (3) or more below that floor, drop one band.
4. **The advanced combo can only raise the result.** Let `A` be the median of every
   dimension level among answers whose slot has `advanced=True`. If `A` outranks the
   current result, raise it by one band, capped at `A`. If `A` is lower, nothing
   happens — the stretch exists to probe the ceiling, and failing above your own
   declared level is not evidence of being worth less.

`by_type` is ordered by `QuestionType` declaration order; `by_topic` by first
appearance in the blueprint. Both skip categories with no answers.

- [ ] **Step 1: Write the failing tests**

Replace the imports and the `assessment` helper region at the top of
`tests/core/test_scoring.py` so the file begins:

```python
from __future__ import annotations

import pytest

from opic.core.metrics import AnswerMetrics
from opic.core.questions import QuestionSlot, QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import (
    AnswerAssessment,
    DimensionScore,
    aggregate,
    dimension_level,
)


def slot(index: int, qtype: QuestionType, topic_id: str | None, advanced: bool = False):
    return QuestionSlot(
        index=index,
        qtype=qtype,
        topic_id=topic_id,
        combo_id=None if topic_id is None else 0,
        advanced=advanced,
        target=ActflLevel.IM2,
    )


def blueprint_of(n: int) -> tuple[QuestionSlot, ...]:
    return tuple(slot(i, QuestionType.DESCRIPTION, "movies") for i in range(n))


def metrics(mean_confidence: float = 0.9, low_rate: float = 0.1) -> AnswerMetrics:
    return AnswerMetrics(
        duration_s=60.0,
        word_count=120,
        words_per_minute=120.0,
        pause_ratio=0.1,
        filler_count=3,
        filler_rate=0.025,
        type_token_ratio=0.6,
        mean_utterance_length=8.0,
        mean_confidence=mean_confidence,
        low_confidence_rate=low_rate,
    )
```

Keep the existing `assessment` and `flat` helpers exactly as they are. Then make
three edits to the existing tests:

1. Every `aggregate(...)` call takes a blueprint first. For a list of `n`
   assessments the call becomes `aggregate(blueprint_of(n), assessments)`.
2. `test_no_assessments_is_refused` becomes `aggregate((), [])`.
3. `test_a_uniform_performance_lands_on_that_level` reads the dimension map by
   subscript today, which no longer works now that it is a tuple of pairs. Change
   its last line from `result.dimension_levels[Dimension.FLUENCY]` to
   `result.level_for(Dimension.FLUENCY)`.

Then append:

```python
def test_dimension_levels_are_an_immutable_sequence_of_pairs():
    result = aggregate(blueprint_of(3), [assessment(i, flat(ActflLevel.IM2)) for i in range(3)])
    assert isinstance(result.dimension_levels, tuple)
    assert result.level_for(Dimension.GRAMMAR) is ActflLevel.IM2
    with pytest.raises(Exception):
        result.dimension_levels[0] = (Dimension.GRAMMAR, ActflLevel.AL)


def test_results_break_down_by_question_type():
    bp = (
        slot(0, QuestionType.DESCRIPTION, "movies"),
        slot(1, QuestionType.HABIT, "movies"),
    )
    assessments = [
        assessment(0, flat(ActflLevel.IH)),
        assessment(1, flat(ActflLevel.IL)),
    ]
    by_type = dict(aggregate(bp, assessments).by_type)
    assert by_type[QuestionType.DESCRIPTION] is ActflLevel.IH
    assert by_type[QuestionType.HABIT] is ActflLevel.IL


def test_results_break_down_by_topic():
    bp = (
        slot(0, QuestionType.DESCRIPTION, "movies"),
        slot(1, QuestionType.DESCRIPTION, "yoga"),
    )
    assessments = [
        assessment(0, flat(ActflLevel.IH)),
        assessment(1, flat(ActflLevel.IL)),
    ]
    by_topic = dict(aggregate(bp, assessments).by_topic)
    assert by_topic["movies"] is ActflLevel.IH
    assert by_topic["yoga"] is ActflLevel.IL


def test_a_strong_advanced_combo_raises_the_final_level():
    bp = (
        slot(0, QuestionType.DESCRIPTION, "movies"),
        slot(1, QuestionType.DESCRIPTION, "yoga", advanced=True),
    )
    assessments = [
        assessment(0, flat(ActflLevel.IM2)),
        assessment(1, flat(ActflLevel.AL)),
    ]
    plain = aggregate(
        (slot(0, QuestionType.DESCRIPTION, "movies"), slot(1, QuestionType.DESCRIPTION, "yoga")),
        assessments,
    )
    raised = aggregate(bp, assessments)
    assert raised.final_level.rank == plain.final_level.rank + 1


def test_a_weak_advanced_combo_does_not_lower_the_final_level():
    bp = (
        slot(0, QuestionType.DESCRIPTION, "movies"),
        slot(1, QuestionType.DESCRIPTION, "yoga", advanced=True),
    )
    assessments = [
        assessment(0, flat(ActflLevel.IH)),
        assessment(1, flat(ActflLevel.NL)),
    ]
    plain = aggregate(
        (slot(0, QuestionType.DESCRIPTION, "movies"), slot(1, QuestionType.DESCRIPTION, "yoga")),
        assessments,
    )
    assert aggregate(bp, assessments).final_level is plain.final_level


def test_an_assessment_without_a_matching_slot_is_refused():
    with pytest.raises(ValueError):
        aggregate(blueprint_of(1), [assessment(0, flat(ActflLevel.IM2)), assessment(5, flat(ActflLevel.IM2))])


def test_a_slot_with_no_assessment_is_refused():
    with pytest.raises(ValueError):
        aggregate(blueprint_of(3), [assessment(0, flat(ActflLevel.IM2))])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/core/test_scoring.py -v`
Expected: FAIL — `aggregate()` takes 1 positional argument but 2 were given.

- [ ] **Step 3: Write the implementation**

In `src/opic/core/scoring.py`, add to the imports:

```python
from opic.core.questions import QuestionSlot, QuestionType
```

Replace the `ExamResult` dataclass with:

```python
@dataclass(frozen=True, slots=True)
class ExamResult:
    final_level: ActflLevel
    dimension_levels: tuple[tuple[Dimension, ActflLevel], ...]
    by_type: tuple[tuple[QuestionType, ActflLevel], ...]
    by_topic: tuple[tuple[str, ActflLevel], ...]
    pronunciation: PronunciationProxy
    assessments: tuple[AnswerAssessment, ...]

    def level_for(self, dimension: Dimension) -> ActflLevel:
        for dim, level in self.dimension_levels:
            if dim is dimension:
                return level
        raise ValueError(f"no level recorded for {dimension.value}")
```

Add this helper above `dimension_level` and rewrite `dimension_level` to use it:

```python
def _median_level(levels: Sequence[ActflLevel]) -> ActflLevel:
    """The median band; even counts take the lower of the two middles."""
    ranks = sorted(level.rank for level in levels)
    if not ranks:
        raise ValueError("cannot take a median of no levels")
    return ActflLevel.from_rank(ranks[(len(ranks) - 1) // 2])


def dimension_level(
    assessments: Sequence[AnswerAssessment],
    dimension: Dimension,
) -> ActflLevel:
    """The median band for one dimension across every answer."""
    return _median_level([a.level_for(dimension) for a in assessments])
```

Replace `aggregate` entirely with:

```python
def _all_levels(assessments: Sequence[AnswerAssessment]) -> list[ActflLevel]:
    return [score.level for a in assessments for score in a.dimension_scores]


def aggregate(
    blueprint: Sequence[QuestionSlot],
    assessments: Sequence[AnswerAssessment],
) -> ExamResult:
    """Collapse per-answer judgements into one level with a fixed rule.

    The blueprint is required because the score depends on what each answer was
    asked: the report breaks down by topic and question type, and the advanced
    combo probes above the declared level.
    """
    if not assessments:
        raise ValueError("cannot aggregate an empty set of assessments")

    slots = {slot.index: slot for slot in blueprint}
    indices = [a.question_index for a in assessments]
    if len(set(indices)) != len(indices):
        raise ValueError("two assessments share a question_index")
    if set(indices) != set(slots):
        missing = sorted(set(slots) - set(indices))
        extra = sorted(set(indices) - set(slots))
        raise ValueError(
            f"assessments do not match the blueprint (missing {missing}, extra {extra})"
        )

    levels = tuple(
        (dimension, dimension_level(assessments, dimension)) for dimension in Dimension
    )
    ranked = dict(levels)

    weighted = sum(
        ranked[dimension].rank * weight
        for dimension, weight in DIMENSION_WEIGHTS.items()
    )
    rank = math.floor(weighted)

    weakest = min(level.rank for level in ranked.values())
    if rank - weakest >= WEAK_DIMENSION_GAP:
        rank -= 1

    advanced = [a for a in assessments if slots[a.question_index].advanced]
    if advanced:
        stretch = _median_level(_all_levels(advanced))
        if stretch.rank > rank:
            rank = min(rank + 1, stretch.rank)

    by_type: list[tuple[QuestionType, ActflLevel]] = []
    for qtype in QuestionType:
        group = [a for a in assessments if slots[a.question_index].qtype is qtype]
        if group:
            by_type.append((qtype, _median_level(_all_levels(group))))

    by_topic: list[tuple[str, ActflLevel]] = []
    for topic_id in dict.fromkeys(
        slots[a.question_index].topic_id for a in assessments
    ):
        if topic_id is None:
            continue
        group = [a for a in assessments if slots[a.question_index].topic_id == topic_id]
        by_topic.append((topic_id, _median_level(_all_levels(group))))

    count = len(assessments)
    pronunciation = PronunciationProxy(
        mean_confidence=sum(a.metrics.mean_confidence for a in assessments) / count,
        low_confidence_rate=sum(a.metrics.low_confidence_rate for a in assessments)
        / count,
        indicative=True,
    )

    return ExamResult(
        final_level=ActflLevel.from_rank(rank),
        dimension_levels=levels,
        by_type=tuple(by_type),
        by_topic=tuple(by_topic),
        pronunciation=pronunciation,
        assessments=tuple(assessments),
    )
```

Note on determinism: `by_topic` iterates `dict.fromkeys` over the assessments in
their given order, which preserves first appearance and never depends on set
ordering.

- [ ] **Step 4: Fix the end-to-end test**

In `tests/core/test_core_end_to_end.py`, change the aggregation call from
`aggregate(assessments)` to `aggregate(blueprint, assessments)`, and replace the
line asserting on `result.dimension_levels` with:

```python
    assert {dim for dim, _ in result.dimension_levels} == set(Dimension)
```

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opic/core/scoring.py tests/core/test_scoring.py tests/core/test_core_end_to_end.py
git commit -m "feat(core): aggregate against the blueprint"
```

---

### Task 6: Gate — guard the new module and prove the breakdowns

**Files:**
- Modify: `tests/test_core_purity.py`
- Modify: `tests/core/test_core_end_to_end.py`

**Interfaces:**
- Consumes: everything Tasks 1 through 5 produced.
- Produces: nothing new. This task is the gate.

- [ ] **Step 1: Write the failing tests**

In `tests/test_core_purity.py`, add `"transcript.py"` to the set inside
`test_the_purity_guard_actually_reads_the_core_modules`, so it reads:

```python
    assert {
        "rubric.py",
        "survey.py",
        "selfassess.py",
        "questions.py",
        "metrics.py",
        "scoring.py",
        "transcript.py",
    } <= modules
```

In `tests/core/test_core_end_to_end.py`, append to the end of the existing test
function:

```python
    assert dict(result.by_type)[QuestionType.SELF_INTRO] is ActflLevel.IM2
    assert len(result.by_topic) == len(
        {slot.topic_id for slot in blueprint if slot.topic_id is not None}
    )
    assert result.level_for(Dimension.FLUENCY) is ActflLevel.IM2
```

and extend that file's import from `opic.core.questions` so it includes
`QuestionType` alongside the names already imported.

- [ ] **Step 2: Run the tests**

Run: `uv run --extra dev pytest tests/test_core_purity.py tests/core/test_core_end_to_end.py -v`
Expected: PASS if Tasks 1 through 5 are clean. A failure here is a real defect in
an earlier task — fix it there, and never by weakening the assertion.

- [ ] **Step 3: Update the README status line**

In `README.md`, replace the two lines under `## Status` with:

```markdown
Phase 1 complete: the pure scoring and exam-planning engine under
`src/opic/core/`. Phase 2 Plan A complete: transcript types, speech-span
metrics, and blueprint-aware aggregation. Adapters, web interface and report
come next.
```

- [ ] **Step 4: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS, every test.

- [ ] **Step 5: Commit**

```bash
git add tests/test_core_purity.py tests/core/test_core_end_to_end.py README.md
git commit -m "test(core): guard the transcript module and the new breakdowns"
```

---

## What Plan B picks up

- The three ports (`TextToSpeech`, `SpeechToText`, `Rater`) in `core/ports.py`.
- The three adapters, the 8B-versus-14B comparison, and the `initial_prompt`
  check that decides whether `filler_count` and `filler_rate` survive.
- The full command-line exam run.
