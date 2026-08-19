# OPIc Core Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure-Python engine that turns a Background Survey plus a
Self Assessment level into a full 15-question exam blueprint, and turns scored
answers into a final ACTFL level with reproducible aggregation.

**Architecture:** Six focused modules under `src/opic/core/`, none of which
imports FastAPI, Ollama, Whisper, Piper, or any network client. Every module is
data-in / data-out over frozen dataclasses, so the whole layer is testable in
milliseconds without a model loaded. Later phases (adapters, web, report) sit on
top of these types without changing them.

**Tech Stack:** Python 3.13, uv, pytest. No runtime dependencies in `core/`.

**Spec:** `docs/superpowers/specs/2026-08-19-opic-simulator-design.md`

## Global Constraints

- Python 3.13. Project managed with `uv`.
- `src/opic/core/` must not import `fastapi`, `httpx`, `requests`, `ollama`,
  `faster_whisper`, `piper`, or `sqlite3`. Task 8 enforces this with a test.
- Import style: every module starts with `from __future__ import annotations`.
- All dataclasses in `core/` are `@dataclass(frozen=True, slots=True)`.
  Collections held by them are tuples, never lists.
- User-facing strings that a Korean test-taker reads are Korean. Field names
  carrying them end in `_ko`. English exam content ends in `_en`.
- ACTFL scale, in this exact order: NL, NM, NH, IL, IM1, IM2, IM3, IH, AL.
- Background Survey Part 4 requires at least 12 selected items in total, with
  per-group minimums: leisure 2, hobby 1, sport 1, travel 1.
- Exam length is exactly 15 questions.
- No randomness without an explicit seed. Same seed plus same input must
  produce the same blueprint, always.
- Run tests with `uv run --extra dev pytest`. Commit after every task.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/opic/__init__.py`
- Create: `src/opic/core/__init__.py`
- Test: `tests/test_package.py`

**Interfaces:**
- Consumes: nothing.
- Produces: importable package `opic` with `opic.__version__: str`. Test command
  `uv run pytest`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_package.py`:

```python
from __future__ import annotations

import opic


def test_package_exposes_version():
    assert isinstance(opic.__version__, str)
    assert opic.__version__ != ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_package.py -v`
Expected: FAIL — no `pyproject.toml` yet, so uv cannot build the environment,
or `ModuleNotFoundError: No module named 'opic'`.

- [ ] **Step 3: Write the minimal implementation**

Create `pyproject.toml`:

```toml
[project]
name = "opic"
version = "0.1.0"
description = "Local OPIc speaking-test simulator"
requires-python = ">=3.13"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/opic"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Create `src/opic/__init__.py`:

```python
from __future__ import annotations

__version__ = "0.1.0"
```

Create `src/opic/core/__init__.py` as an empty file.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev pytest tests/test_package.py -v`
Expected: PASS, 1 test.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/opic tests/test_package.py
git commit -m "chore: scaffold opic package with pytest"
```

---

### Task 2: ACTFL scale and scoring dimensions

**Files:**
- Create: `src/opic/core/rubric.py`
- Test: `tests/core/test_rubric.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ActflLevel` — `Enum` with members NL=0, NM=1, NH=2, IL=3, IM1=4, IM2=5,
    IM3=6, IH=7, AL=8; property `rank -> int`; classmethod
    `from_rank(rank: int) -> ActflLevel` that clamps out-of-range input.
  - `Dimension` — `Enum` with FLUENCY, GRAMMAR, VOCABULARY, COHERENCE,
    RELEVANCE.
  - `DIMENSION_WEIGHTS: dict[Dimension, float]` summing to 1.0.
  - `DIMENSION_LABELS_KO: dict[Dimension, str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/__init__.py` as an empty file, then `tests/core/test_rubric.py`:

```python
from __future__ import annotations

import pytest

from opic.core.rubric import (
    DIMENSION_LABELS_KO,
    DIMENSION_WEIGHTS,
    ActflLevel,
    Dimension,
)


def test_levels_are_ordered_low_to_high():
    ranks = [level.rank for level in ActflLevel]
    assert ranks == sorted(ranks)
    assert [level.name for level in ActflLevel] == [
        "NL", "NM", "NH", "IL", "IM1", "IM2", "IM3", "IH", "AL",
    ]


def test_from_rank_round_trips():
    for level in ActflLevel:
        assert ActflLevel.from_rank(level.rank) is level


@pytest.mark.parametrize(
    ("rank", "expected"),
    [(-5, ActflLevel.NL), (99, ActflLevel.AL)],
)
def test_from_rank_clamps_out_of_range(rank, expected):
    assert ActflLevel.from_rank(rank) is expected


def test_dimension_weights_cover_every_dimension_and_sum_to_one():
    assert set(DIMENSION_WEIGHTS) == set(Dimension)
    assert sum(DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_dimension_has_a_korean_label():
    assert set(DIMENSION_LABELS_KO) == set(Dimension)
    assert all(label.strip() for label in DIMENSION_LABELS_KO.values())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_rubric.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.core.rubric'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/opic/core/rubric.py`:

```python
from __future__ import annotations

from enum import Enum


class ActflLevel(Enum):
    """The OPIc proficiency scale, ordered from lowest to highest."""

    NL = 0
    NM = 1
    NH = 2
    IL = 3
    IM1 = 4
    IM2 = 5
    IM3 = 6
    IH = 7
    AL = 8

    @property
    def rank(self) -> int:
        return self.value

    @classmethod
    def from_rank(cls, rank: int) -> ActflLevel:
        lowest = min(level.value for level in cls)
        highest = max(level.value for level in cls)
        return cls(max(lowest, min(highest, rank)))


class Dimension(Enum):
    """What the evaluator judges, one axis at a time."""

    FLUENCY = "fluency"
    GRAMMAR = "grammar"
    VOCABULARY = "vocabulary"
    COHERENCE = "coherence"
    RELEVANCE = "relevance"


DIMENSION_WEIGHTS: dict[Dimension, float] = {
    Dimension.FLUENCY: 0.25,
    Dimension.GRAMMAR: 0.20,
    Dimension.VOCABULARY: 0.20,
    Dimension.COHERENCE: 0.20,
    Dimension.RELEVANCE: 0.15,
}

DIMENSION_LABELS_KO: dict[Dimension, str] = {
    Dimension.FLUENCY: "유창성",
    Dimension.GRAMMAR: "문법",
    Dimension.VOCABULARY: "어휘",
    Dimension.COHERENCE: "구성력",
    Dimension.RELEVANCE: "질문 적합성",
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_rubric.py -v`
Expected: PASS, 6 tests (the parametrised case counts twice).

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/rubric.py tests/core/
git commit -m "feat(core): add ACTFL scale and scoring dimensions"
```

---

### Task 3: Background Survey catalog and validation

**Files:**
- Create: `src/opic/core/survey.py`
- Test: `tests/core/test_survey.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Occupation` — BUSINESS, HOME_OFFICE, TEACHER, NO_EXPERIENCE.
  - `Housing` — ALONE, WITH_ROOMMATE, WITH_FAMILY, DORM, BARRACKS.
  - `TopicGroup` — LEISURE, HOBBY, SPORT, TRAVEL.
  - `SurveyItem(id: str, group: TopicGroup, label_ko: str, label_en: str)`.
  - `SURVEY_ITEMS: tuple[SurveyItem, ...]` and `ITEMS_BY_ID: dict[str, SurveyItem]`.
  - `MIN_TOTAL_ITEMS: int` and `GROUP_MINIMUMS: dict[TopicGroup, int]`.
  - `SurveyAnswers(occupation, is_student, housing, selected_item_ids: tuple[str, ...])`.
  - `SurveyError` — UNKNOWN_ITEM, TOO_FEW_ITEMS, GROUP_MINIMUM.
  - `ValidationIssue(error: SurveyError, detail: str)`.
  - `validate_survey(answers: SurveyAnswers) -> tuple[ValidationIssue, ...]` —
    empty tuple means valid.
  - `selected_items(answers: SurveyAnswers) -> tuple[SurveyItem, ...]` — raises
    `KeyError` on an unknown id, so callers validate first.

The catalog below is transcribed from the reference screenshots in `evidence/`.
It is the seed set; adding more items later is a data change, not a code change.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_survey.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_survey.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.core.survey'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/opic/core/survey.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Occupation(Enum):
    BUSINESS = "business"
    HOME_OFFICE = "home_office"
    TEACHER = "teacher"
    NO_EXPERIENCE = "no_experience"


class Housing(Enum):
    ALONE = "alone"
    WITH_ROOMMATE = "with_roommate"
    WITH_FAMILY = "with_family"
    DORM = "dorm"
    BARRACKS = "barracks"


class TopicGroup(Enum):
    LEISURE = "leisure"
    HOBBY = "hobby"
    SPORT = "sport"
    TRAVEL = "travel"


@dataclass(frozen=True, slots=True)
class SurveyItem:
    id: str
    group: TopicGroup
    label_ko: str
    label_en: str


SURVEY_ITEMS: tuple[SurveyItem, ...] = (
    SurveyItem("movies", TopicGroup.LEISURE, "영화보기", "watching movies"),
    SurveyItem("clubbing", TopicGroup.LEISURE, "클럽/나이트클럽 가기", "going to clubs"),
    SurveyItem("live_shows", TopicGroup.LEISURE, "공연보기", "seeing live performances"),
    SurveyItem("concerts", TopicGroup.LEISURE, "콘서트보기", "going to concerts"),
    SurveyItem("museums", TopicGroup.LEISURE, "박물관가기", "visiting museums"),
    SurveyItem("parks", TopicGroup.LEISURE, "공원가기", "going to parks"),
    SurveyItem("camping", TopicGroup.LEISURE, "캠핑하기", "camping"),
    SurveyItem("beach", TopicGroup.LEISURE, "해변가기", "going to the beach"),
    SurveyItem("watching_sports", TopicGroup.LEISURE, "스포츠 관람", "watching sports"),
    SurveyItem("home_improvement", TopicGroup.LEISURE, "주거 개선", "home improvement"),
    SurveyItem("reading_to_kids", TopicGroup.HOBBY, "아이에게 책 읽어주기", "reading to children"),
    SurveyItem("listening_music", TopicGroup.HOBBY, "음악 감상하기", "listening to music"),
    SurveyItem("playing_instrument", TopicGroup.HOBBY, "악기 연주하기", "playing an instrument"),
    SurveyItem("singing", TopicGroup.HOBBY, "혼자 노래부르거나 합창하기", "singing"),
    SurveyItem("dancing", TopicGroup.HOBBY, "춤추기", "dancing"),
    SurveyItem("writing", TopicGroup.HOBBY, "글쓰기(편지, 단문, 시 등)", "writing"),
    SurveyItem("drawing", TopicGroup.HOBBY, "그림 그리기", "drawing"),
    SurveyItem("cooking", TopicGroup.HOBBY, "요리하기", "cooking"),
    SurveyItem("pets", TopicGroup.HOBBY, "애완동물 기르기", "keeping pets"),
    SurveyItem("cricket", TopicGroup.SPORT, "크리켓", "cricket"),
    SurveyItem("golf", TopicGroup.SPORT, "골프", "golf"),
    SurveyItem("volleyball", TopicGroup.SPORT, "배구", "volleyball"),
    SurveyItem("tennis", TopicGroup.SPORT, "테니스", "tennis"),
    SurveyItem("badminton", TopicGroup.SPORT, "배드민턴", "badminton"),
    SurveyItem("table_tennis", TopicGroup.SPORT, "탁구", "table tennis"),
    SurveyItem("swimming", TopicGroup.SPORT, "수영", "swimming"),
    SurveyItem("cycling", TopicGroup.SPORT, "자전거", "cycling"),
    SurveyItem("skiing", TopicGroup.SPORT, "스키/스노우보드", "skiing or snowboarding"),
    SurveyItem("ice_skating", TopicGroup.SPORT, "아이스 스케이트", "ice skating"),
    SurveyItem("jogging", TopicGroup.SPORT, "조깅", "jogging"),
    SurveyItem("walking", TopicGroup.SPORT, "걷기", "walking"),
    SurveyItem("yoga", TopicGroup.SPORT, "요가", "yoga"),
    SurveyItem("hiking", TopicGroup.SPORT, "하이킹/트레킹", "hiking"),
    SurveyItem("fishing", TopicGroup.SPORT, "낚시", "fishing"),
    SurveyItem("gym", TopicGroup.SPORT, "헬스", "working out at a gym"),
    SurveyItem("no_sport", TopicGroup.SPORT, "운동을 전혀 하지 않음", "no sports at all"),
    SurveyItem("domestic_business_trip", TopicGroup.TRAVEL, "국내출장", "domestic business trips"),
    SurveyItem("overseas_business_trip", TopicGroup.TRAVEL, "해외출장", "overseas business trips"),
    SurveyItem("staycation", TopicGroup.TRAVEL, "집에서 보내는 휴가", "vacations at home"),
    SurveyItem("domestic_travel", TopicGroup.TRAVEL, "국내 여행", "domestic travel"),
    SurveyItem("overseas_travel", TopicGroup.TRAVEL, "해외 여행", "overseas travel"),
)

ITEMS_BY_ID: dict[str, SurveyItem] = {item.id: item for item in SURVEY_ITEMS}

MIN_TOTAL_ITEMS = 12

GROUP_MINIMUMS: dict[TopicGroup, int] = {
    TopicGroup.LEISURE: 2,
    TopicGroup.HOBBY: 1,
    TopicGroup.SPORT: 1,
    TopicGroup.TRAVEL: 1,
}


@dataclass(frozen=True, slots=True)
class SurveyAnswers:
    occupation: Occupation
    is_student: bool
    housing: Housing
    selected_item_ids: tuple[str, ...]


class SurveyError(Enum):
    UNKNOWN_ITEM = "unknown_item"
    TOO_FEW_ITEMS = "too_few_items"
    GROUP_MINIMUM = "group_minimum"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    error: SurveyError
    detail: str


def validate_survey(answers: SurveyAnswers) -> tuple[ValidationIssue, ...]:
    """Return every rule the selection breaks. An empty tuple means valid."""
    issues: list[ValidationIssue] = []

    unknown = [
        item_id for item_id in answers.selected_item_ids if item_id not in ITEMS_BY_ID
    ]
    for item_id in unknown:
        issues.append(ValidationIssue(SurveyError.UNKNOWN_ITEM, item_id))

    known = [
        ITEMS_BY_ID[item_id]
        for item_id in answers.selected_item_ids
        if item_id in ITEMS_BY_ID
    ]

    if len(known) < MIN_TOTAL_ITEMS:
        issues.append(
            ValidationIssue(
                SurveyError.TOO_FEW_ITEMS,
                f"{len(known)}/{MIN_TOTAL_ITEMS}",
            )
        )

    for group, minimum in GROUP_MINIMUMS.items():
        chosen = sum(1 for item in known if item.group is group)
        if chosen < minimum:
            issues.append(
                ValidationIssue(
                    SurveyError.GROUP_MINIMUM,
                    f"{group.value}: {chosen}/{minimum}",
                )
            )

    return tuple(issues)


def selected_items(answers: SurveyAnswers) -> tuple[SurveyItem, ...]:
    """Resolve the selection to catalog entries, preserving selection order."""
    return tuple(ITEMS_BY_ID[item_id] for item_id in answers.selected_item_ids)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_survey.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/survey.py tests/core/test_survey.py
git commit -m "feat(core): add background survey catalog and validation"
```

---

### Task 4: Self Assessment levels

**Files:**
- Create: `src/opic/core/selfassess.py`
- Test: `tests/core/test_selfassess.py`

**Interfaces:**
- Consumes: `ActflLevel` from `opic.core.rubric`.
- Produces:
  - `SelfAssessOption(level: int, description_ko: str, sample_audio_id: str)`.
  - `SELF_ASSESS_OPTIONS: tuple[SelfAssessOption, ...]` — exactly six, levels 1
    through 6 in order.
  - `LEVEL_TO_TARGET: dict[int, ActflLevel]`.
  - `target_level(level: int) -> ActflLevel` — raises `ValueError` outside 1..6.

The six descriptions are transcribed from `evidence/Screenshot at Aug 19
09-45-33.png`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_selfassess.py`:

```python
from __future__ import annotations

import pytest

from opic.core.rubric import ActflLevel
from opic.core.selfassess import (
    LEVEL_TO_TARGET,
    SELF_ASSESS_OPTIONS,
    target_level,
)


def test_there_are_exactly_six_options_numbered_in_order():
    assert [option.level for option in SELF_ASSESS_OPTIONS] == [1, 2, 3, 4, 5, 6]


def test_every_option_has_korean_text_and_a_sample_audio_id():
    for option in SELF_ASSESS_OPTIONS:
        assert option.description_ko.strip()
        assert option.sample_audio_id.strip()


def test_sample_audio_ids_are_unique():
    ids = [option.sample_audio_id for option in SELF_ASSESS_OPTIONS]
    assert len(ids) == len(set(ids))


def test_targets_rise_with_the_self_assessed_level():
    ranks = [LEVEL_TO_TARGET[level].rank for level in range(1, 7)]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 6


def test_target_level_maps_the_extremes():
    assert target_level(1) is ActflLevel.NL
    assert target_level(6) is ActflLevel.AL


@pytest.mark.parametrize("level", [0, 7, -1])
def test_target_level_rejects_levels_outside_the_scale(level):
    with pytest.raises(ValueError):
        target_level(level)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_selfassess.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.core.selfassess'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/opic/core/selfassess.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from opic.core.rubric import ActflLevel


@dataclass(frozen=True, slots=True)
class SelfAssessOption:
    level: int
    description_ko: str
    sample_audio_id: str


SELF_ASSESS_OPTIONS: tuple[SelfAssessOption, ...] = (
    SelfAssessOption(
        1,
        "나는 10단어 이하의 단어로 말할 수 있습니다.",
        "sample_1",
    ),
    SelfAssessOption(
        2,
        "나는 기본적인 물건, 색깔, 요일, 음식, 의류, 숫자 등을 말할 수 있습니다. "
        "나는 항상 완벽한 문장을 구사하지는 못하고 간단한 질문도 하기 어렵습니다.",
        "sample_2",
    ),
    SelfAssessOption(
        3,
        "나는 나 자신, 직장, 친숙한 사람과 장소, 일상에 대한 기본적인 정보를 "
        "간단한 문장으로 전달할 수 있습니다. 간단한 질문을 할 수 있습니다.",
        "sample_3",
    ),
    SelfAssessOption(
        4,
        "나는 나 자신, 일상, 일/학교, 취미에 대해 간단한 대화를 할 수 있습니다. "
        "나는 이런 친숙한 주제와 일상에 대해 일련의 간단한 문장들을 쉽게 만들어 "
        "낼 수 있습니다. 내가 필요한 것을 얻기 위한 질문도 할 수 있습니다.",
        "sample_4",
    ),
    SelfAssessOption(
        5,
        "나는 친숙한 주제와 가정, 일/학교, 개인 및 사회적 관심사에 대해 대화할 수 "
        "있습니다. 나는 일어난 일과 일어나고 있는 일, 일어날 일에 대해 문장을 "
        "연결하여 말할 수 있습니다. 필요한 경우 설명도 할 수 있습니다. 일상 "
        "생활에서 예기치 못한 상황이 발생하더라도 임기응변으로 대처할 수 있습니다.",
        "sample_5",
    ),
    SelfAssessOption(
        6,
        "나는 일/학교, 개인적인 관심사, 시사 문제에 대한 어떤 대화나 토론에도 "
        "자신 있게 참여할 수 있습니다. 나는 대부분의 주제에 관해 높은 수준의 "
        "정확성과 폭넓은 어휘로 상세히 설명할 수 있습니다.",
        "sample_6",
    ),
)

LEVEL_TO_TARGET: dict[int, ActflLevel] = {
    1: ActflLevel.NL,
    2: ActflLevel.NM,
    3: ActflLevel.NH,
    4: ActflLevel.IM1,
    5: ActflLevel.IH,
    6: ActflLevel.AL,
}


def target_level(level: int) -> ActflLevel:
    """The proficiency the generated questions aim at, given the self assessment."""
    if level not in LEVEL_TO_TARGET:
        raise ValueError(f"self assessment level must be 1..6, got {level!r}")
    return LEVEL_TO_TARGET[level]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_selfassess.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/selfassess.py tests/core/test_selfassess.py
git commit -m "feat(core): add self assessment levels and target mapping"
```

---

### Task 5: Exam blueprint builder

**Files:**
- Create: `src/opic/core/questions.py`
- Test: `tests/core/test_questions.py`

**Interfaces:**
- Consumes: `SurveyAnswers`, `selected_items`, `validate_survey` from
  `opic.core.survey`; `target_level` from `opic.core.selfassess`.
- Produces:
  - `QuestionType` — SELF_INTRO, DESCRIPTION, HABIT, EXPERIENCE,
    ROLEPLAY_SETUP, ROLEPLAY_FOLLOWUP.
  - `QuestionSlot(index: int, qtype: QuestionType, topic_id: str | None,
    combo_id: int | None, advanced: bool, target: ActflLevel)`.
  - `EXAM_LENGTH: int` (15), `COMBO_COUNT: int` (4),
    `COMBO_TYPES: tuple[QuestionType, ...]`.
  - `build_blueprint(answers: SurveyAnswers, self_assess_level: int, seed: int)
    -> tuple[QuestionSlot, ...]` — raises `ValueError` if the survey is invalid.

Layout: slot 0 is the self-introduction; slots 1 through 12 are four combos of
three (description, habit, experience) over four distinct selected topics; slots
13 and 14 are the role-play pair. The last combo always carries `advanced=True`
and a target one band above the self-assessed target, which is how the exam
probes above the declared level.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_questions.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_questions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.core.questions'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/opic/core/questions.py`:

```python
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from opic.core.rubric import ActflLevel
from opic.core.selfassess import target_level
from opic.core.survey import SurveyAnswers, selected_items, validate_survey


class QuestionType(Enum):
    SELF_INTRO = "self_intro"
    DESCRIPTION = "description"
    HABIT = "habit"
    EXPERIENCE = "experience"
    ROLEPLAY_SETUP = "roleplay_setup"
    ROLEPLAY_FOLLOWUP = "roleplay_followup"


@dataclass(frozen=True, slots=True)
class QuestionSlot:
    index: int
    qtype: QuestionType
    topic_id: str | None
    combo_id: int | None
    advanced: bool
    target: ActflLevel


COMBO_TYPES: tuple[QuestionType, ...] = (
    QuestionType.DESCRIPTION,
    QuestionType.HABIT,
    QuestionType.EXPERIENCE,
)
COMBO_COUNT = 4
EXAM_LENGTH = 1 + COMBO_COUNT * len(COMBO_TYPES) + 2


def build_blueprint(
    answers: SurveyAnswers,
    self_assess_level: int,
    seed: int,
) -> tuple[QuestionSlot, ...]:
    """Lay out the whole exam before a single question is generated.

    Building the shape up front keeps the LLM off the critical path: by the time
    the test-taker reaches Setup, every question is known and its audio can be
    synthesised in advance.
    """
    issues = validate_survey(answers)
    if issues:
        detail = ", ".join(f"{issue.error.value}({issue.detail})" for issue in issues)
        raise ValueError(f"invalid survey: {detail}")

    base = target_level(self_assess_level)
    stretched = ActflLevel.from_rank(base.rank + 1)

    rng = random.Random(seed)
    pool = [item.id for item in selected_items(answers)]
    combo_topics = rng.sample(pool, COMBO_COUNT)

    remaining = [topic for topic in pool if topic not in combo_topics]
    roleplay_topic = rng.choice(remaining or pool)

    slots: list[QuestionSlot] = [
        QuestionSlot(
            index=0,
            qtype=QuestionType.SELF_INTRO,
            topic_id=None,
            combo_id=None,
            advanced=False,
            target=base,
        )
    ]

    for combo_id, topic_id in enumerate(combo_topics):
        advanced = combo_id == COMBO_COUNT - 1
        for qtype in COMBO_TYPES:
            slots.append(
                QuestionSlot(
                    index=len(slots),
                    qtype=qtype,
                    topic_id=topic_id,
                    combo_id=combo_id,
                    advanced=advanced,
                    target=stretched if advanced else base,
                )
            )

    for qtype in (QuestionType.ROLEPLAY_SETUP, QuestionType.ROLEPLAY_FOLLOWUP):
        slots.append(
            QuestionSlot(
                index=len(slots),
                qtype=qtype,
                topic_id=roleplay_topic,
                combo_id=None,
                advanced=False,
                target=base,
            )
        )

    return tuple(slots)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_questions.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/questions.py tests/core/test_questions.py
git commit -m "feat(core): build the deterministic exam blueprint"
```

---

### Task 6: Objective speech metrics

**Files:**
- Create: `src/opic/core/metrics.py`
- Test: `tests/core/test_metrics.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Word(text: str, start: float, end: float, probability: float)` — the shape
    faster-whisper returns per word; the adapter in a later phase maps onto it.
  - `AnswerMetrics` with fields `duration_s`, `word_count`,
    `words_per_minute`, `pause_ratio`, `filler_count`, `filler_rate`,
    `type_token_ratio`, `mean_utterance_length`, `mean_confidence`,
    `low_confidence_rate` (all `float` except the two counts, which are `int`).
  - `FILLERS: frozenset[str]`, `PAUSE_THRESHOLD_S: float` (0.5),
    `LOW_CONFIDENCE_THRESHOLD: float` (0.6).
  - `compute_metrics(words: Sequence[Word], duration_s: float) -> AnswerMetrics`.

These numbers are arithmetic, so they are computed here and handed to the model
as facts. The model is never asked to count.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_metrics.py`:

```python
from __future__ import annotations

import pytest

from opic.core.metrics import Word, compute_metrics


def speech(texts: list[str], step: float = 0.5, probability: float = 0.9) -> list[Word]:
    return [
        Word(text=text, start=i * step, end=i * step + step / 2, probability=probability)
        for i, text in enumerate(texts)
    ]


def test_empty_speech_yields_zeroed_metrics():
    metrics = compute_metrics([], duration_s=10.0)
    assert metrics.word_count == 0
    assert metrics.words_per_minute == 0.0
    assert metrics.type_token_ratio == 0.0
    assert metrics.pause_ratio == 0.0
    assert metrics.mean_utterance_length == 0.0


def test_words_per_minute_counts_words_over_the_recording_length():
    words = speech(["one"] * 30)
    metrics = compute_metrics(words, duration_s=60.0)
    assert metrics.words_per_minute == pytest.approx(30.0)


def test_pause_ratio_measures_silence_between_words():
    words = [
        Word("hello", 0.0, 1.0, 0.9),
        Word("world", 4.0, 5.0, 0.9),
    ]
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.pause_ratio == pytest.approx(0.3)


def test_short_gaps_are_not_pauses():
    words = [
        Word("hello", 0.0, 1.0, 0.9),
        Word("world", 1.2, 2.0, 0.9),
    ]
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.pause_ratio == 0.0


def test_fillers_are_counted_case_insensitively_and_without_punctuation():
    words = speech(["Um,", "I", "uh", "think", "so"])
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.filler_count == 2
    assert metrics.filler_rate == pytest.approx(2 / 5)


def test_common_words_that_are_not_hesitations_are_not_fillers():
    words = speech(["I", "like", "it", "so", "well"])
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.filler_count == 0


def test_type_token_ratio_measures_lexical_variety():
    words = speech(["cat", "cat", "dog", "bird"])
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.type_token_ratio == pytest.approx(0.75)


def test_mean_utterance_length_splits_the_answer_on_pauses():
    words = [
        Word("I", 0.0, 0.3, 0.9),
        Word("think", 0.4, 0.8, 0.9),
        Word("so", 3.0, 3.4, 0.9),
    ]
    metrics = compute_metrics(words, duration_s=10.0)
    assert metrics.mean_utterance_length == pytest.approx(1.5)


def test_confidence_metrics_flag_doubtful_words():
    words = [
        Word("clear", 0.0, 0.5, 0.95),
        Word("mumbled", 1.0, 1.5, 0.25),
    ]
    metrics = compute_metrics(words, duration_s=5.0)
    assert metrics.mean_confidence == pytest.approx(0.6)
    assert metrics.low_confidence_rate == pytest.approx(0.5)


def test_a_non_positive_duration_is_refused():
    with pytest.raises(ValueError):
        compute_metrics(speech(["hello"]), duration_s=0.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.core.metrics'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/opic/core/metrics.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

PAUSE_THRESHOLD_S = 0.5
LOW_CONFIDENCE_THRESHOLD = 0.6

# Only true hesitation markers. Words like "like", "so" and "well" carry
# meaning far more often than they stall, and counting them would punish
# ordinary English.
FILLERS: frozenset[str] = frozenset(
    {"uh", "um", "umm", "erm", "er", "ah", "eh", "mm", "hmm", "mhm"}
)

_STRIP = ".,!?;:\"'()[]…-"


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: float
    end: float
    probability: float


@dataclass(frozen=True, slots=True)
class AnswerMetrics:
    duration_s: float
    word_count: int
    words_per_minute: float
    pause_ratio: float
    filler_count: int
    filler_rate: float
    type_token_ratio: float
    mean_utterance_length: float
    mean_confidence: float
    low_confidence_rate: float


def _normalise(text: str) -> str:
    return text.strip().strip(_STRIP).lower()


def compute_metrics(words: Sequence[Word], duration_s: float) -> AnswerMetrics:
    """Derive the objective half of the score from word-level timings.

    Everything here is arithmetic, which is exactly why it does not go to the
    model: a local LLM will happily invent a words-per-minute figure.
    """
    if duration_s <= 0:
        raise ValueError(f"duration_s must be positive, got {duration_s!r}")

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

    tokens = [_normalise(word.text) for word in words]
    spoken = [token for token in tokens if token]

    paused = 0.0
    breaks = 0
    for earlier, later in zip(words, words[1:], strict=False):
        gap = later.start - earlier.end
        if gap > PAUSE_THRESHOLD_S:
            paused += gap
            breaks += 1

    fillers = sum(1 for token in spoken if token in FILLERS)
    confidences = [word.probability for word in words]
    doubtful = sum(1 for value in confidences if value < LOW_CONFIDENCE_THRESHOLD)

    return AnswerMetrics(
        duration_s=duration_s,
        word_count=count,
        words_per_minute=count / duration_s * 60.0,
        pause_ratio=min(1.0, paused / duration_s),
        filler_count=fillers,
        filler_rate=fillers / count,
        type_token_ratio=len(set(spoken)) / len(spoken) if spoken else 0.0,
        mean_utterance_length=count / (breaks + 1),
        mean_confidence=sum(confidences) / count,
        low_confidence_rate=doubtful / count,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_metrics.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/metrics.py tests/core/test_metrics.py
git commit -m "feat(core): compute objective speech metrics from word timings"
```

---

### Task 7: Score aggregation

**Files:**
- Create: `src/opic/core/scoring.py`
- Test: `tests/core/test_scoring.py`

**Interfaces:**
- Consumes: `ActflLevel`, `Dimension`, `DIMENSION_WEIGHTS` from
  `opic.core.rubric`; `AnswerMetrics` from `opic.core.metrics`.
- Produces:
  - `Evidence(quote: str, issue_ko: str, correction_en: str)`.
  - `DimensionScore(dimension, level, comment_ko, evidence: tuple[Evidence, ...])`.
  - `AnswerAssessment(question_index: int, dimension_scores: tuple[DimensionScore, ...],
    metrics: AnswerMetrics)`.
  - `PronunciationProxy(mean_confidence: float, low_confidence_rate: float,
    indicative: bool)`.
  - `ExamResult(final_level, dimension_levels: dict[Dimension, ActflLevel],
    pronunciation, assessments: tuple[AnswerAssessment, ...])`.
  - `WEAK_DIMENSION_GAP: int` (3).
  - `dimension_level(assessments, dimension) -> ActflLevel` — lower median.
  - `aggregate(assessments: Sequence[AnswerAssessment]) -> ExamResult` — raises
    `ValueError` on an empty sequence or an assessment missing a dimension.

Aggregation is a fixed rule, not a model opinion, so re-running the evaluation
over the same audio always lands on the same level:

1. Per dimension, take the median of that dimension's levels across answers.
   With an even count, take the lower of the two middles.
2. Take the weighted mean of those dimension ranks and floor it.
3. If any single dimension sits `WEAK_DIMENSION_GAP` bands or more below that
   floor, drop the final level by one — a serious weakness in one axis caps the
   result rather than being averaged away.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_scoring.py`:

```python
from __future__ import annotations

import pytest

from opic.core.metrics import AnswerMetrics
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import (
    AnswerAssessment,
    DimensionScore,
    aggregate,
    dimension_level,
)


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


def assessment(
    index: int,
    levels: dict[Dimension, ActflLevel],
    mean_confidence: float = 0.9,
    low_rate: float = 0.1,
) -> AnswerAssessment:
    return AnswerAssessment(
        question_index=index,
        dimension_scores=tuple(
            DimensionScore(
                dimension=dimension,
                level=levels[dimension],
                comment_ko="설명",
                evidence=(),
            )
            for dimension in Dimension
        ),
        metrics=metrics(mean_confidence, low_rate),
    )


def flat(level: ActflLevel) -> dict[Dimension, ActflLevel]:
    return {dimension: level for dimension in Dimension}


def test_dimension_level_takes_the_median_across_answers():
    assessments = [
        assessment(0, flat(ActflLevel.IL)),
        assessment(1, flat(ActflLevel.IM2)),
        assessment(2, flat(ActflLevel.IM3)),
    ]
    assert dimension_level(assessments, Dimension.GRAMMAR) is ActflLevel.IM2


def test_an_even_count_takes_the_lower_middle():
    assessments = [
        assessment(0, flat(ActflLevel.IL)),
        assessment(1, flat(ActflLevel.IM2)),
    ]
    assert dimension_level(assessments, Dimension.GRAMMAR) is ActflLevel.IL


def test_a_uniform_performance_lands_on_that_level():
    assessments = [assessment(i, flat(ActflLevel.IM2)) for i in range(3)]
    result = aggregate(assessments)
    assert result.final_level is ActflLevel.IM2
    assert result.dimension_levels[Dimension.FLUENCY] is ActflLevel.IM2


def test_one_severely_weak_dimension_pulls_the_final_level_down():
    levels = flat(ActflLevel.IH)
    levels[Dimension.GRAMMAR] = ActflLevel.NH
    assessments = [assessment(i, levels) for i in range(3)]
    result = aggregate(assessments)
    strong = aggregate([assessment(i, flat(ActflLevel.IH)) for i in range(3)])
    assert result.final_level.rank < strong.final_level.rank


def test_the_pronunciation_proxy_is_averaged_and_flagged_as_indicative():
    assessments = [
        assessment(0, flat(ActflLevel.IM2), mean_confidence=0.8, low_rate=0.2),
        assessment(1, flat(ActflLevel.IM2), mean_confidence=0.6, low_rate=0.4),
    ]
    result = aggregate(assessments)
    assert result.pronunciation.mean_confidence == pytest.approx(0.7)
    assert result.pronunciation.low_confidence_rate == pytest.approx(0.3)
    assert result.pronunciation.indicative is True


def test_aggregation_is_reproducible():
    assessments = [assessment(i, flat(ActflLevel.IM1)) for i in range(4)]
    assert aggregate(assessments) == aggregate(assessments)


def test_no_assessments_is_refused():
    with pytest.raises(ValueError):
        aggregate([])


def test_an_assessment_missing_a_dimension_is_refused():
    broken = AnswerAssessment(
        question_index=0,
        dimension_scores=(
            DimensionScore(Dimension.FLUENCY, ActflLevel.IM2, "설명", ()),
        ),
        metrics=metrics(),
    )
    with pytest.raises(ValueError):
        aggregate([broken])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.core.scoring'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/opic/core/scoring.py`:

```python
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from opic.core.metrics import AnswerMetrics
from opic.core.rubric import DIMENSION_WEIGHTS, ActflLevel, Dimension

WEAK_DIMENSION_GAP = 3


@dataclass(frozen=True, slots=True)
class Evidence:
    quote: str
    issue_ko: str
    correction_en: str


@dataclass(frozen=True, slots=True)
class DimensionScore:
    dimension: Dimension
    level: ActflLevel
    comment_ko: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerAssessment:
    question_index: int
    dimension_scores: tuple[DimensionScore, ...]
    metrics: AnswerMetrics

    def level_for(self, dimension: Dimension) -> ActflLevel:
        for score in self.dimension_scores:
            if score.dimension is dimension:
                return score.level
        raise ValueError(
            f"answer {self.question_index} has no score for {dimension.value}"
        )


@dataclass(frozen=True, slots=True)
class PronunciationProxy:
    """A rough signal, never a band.

    Whisper does not measure pronunciation. Transcription confidence correlates
    with it loosely, so it is reported as a hint and labelled as such.
    """

    mean_confidence: float
    low_confidence_rate: float
    indicative: bool = True


@dataclass(frozen=True, slots=True)
class ExamResult:
    final_level: ActflLevel
    dimension_levels: dict[Dimension, ActflLevel]
    pronunciation: PronunciationProxy
    assessments: tuple[AnswerAssessment, ...]


def dimension_level(
    assessments: Sequence[AnswerAssessment],
    dimension: Dimension,
) -> ActflLevel:
    """The median band for one dimension; even counts take the lower middle."""
    ranks = sorted(
        assessment.level_for(dimension).rank for assessment in assessments
    )
    if not ranks:
        raise ValueError("cannot take a median of no assessments")
    return ActflLevel.from_rank(ranks[(len(ranks) - 1) // 2])


def aggregate(assessments: Sequence[AnswerAssessment]) -> ExamResult:
    """Collapse per-answer judgements into one level with a fixed rule."""
    if not assessments:
        raise ValueError("cannot aggregate an empty set of assessments")

    levels = {
        dimension: dimension_level(assessments, dimension) for dimension in Dimension
    }

    weighted = sum(
        levels[dimension].rank * weight
        for dimension, weight in DIMENSION_WEIGHTS.items()
    )
    rank = math.floor(weighted)

    weakest = min(level.rank for level in levels.values())
    if rank - weakest >= WEAK_DIMENSION_GAP:
        rank -= 1

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
        pronunciation=pronunciation,
        assessments=tuple(assessments),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run --extra dev pytest tests/core/test_scoring.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add src/opic/core/scoring.py tests/core/test_scoring.py
git commit -m "feat(core): aggregate answer assessments into a final ACTFL level"
```

---

### Task 8: End-to-end core test and the purity guard

**Files:**
- Create: `tests/core/test_core_end_to_end.py`
- Create: `tests/test_core_purity.py`
- Modify: `README.md` (create it if absent)

**Interfaces:**
- Consumes: every public name produced by Tasks 2 through 7.
- Produces: nothing new. This task is the gate that proves the layer holds
  together and stays free of infrastructure.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_core_end_to_end.py`:

```python
from __future__ import annotations

from opic.core.metrics import Word, compute_metrics
from opic.core.questions import EXAM_LENGTH, build_blueprint
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
    )
    assert validate_survey(answers) == ()

    blueprint = build_blueprint(answers, self_assess_level=4, seed=42)
    assert len(blueprint) == EXAM_LENGTH

    words = [
        Word(text=text, start=i * 0.4, end=i * 0.4 + 0.3, probability=0.88)
        for i, text in enumerate("I usually go to the beach on weekends".split())
    ]
    metrics = compute_metrics(words, duration_s=30.0)

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

    result = aggregate(assessments)
    assert result.final_level is ActflLevel.IM2
    assert len(result.assessments) == EXAM_LENGTH
    assert result.pronunciation.indicative is True
    assert set(result.dimension_levels) == set(Dimension)
```

Create `tests/test_core_purity.py`:

```python
from __future__ import annotations

import ast
import pathlib

FORBIDDEN = {
    "fastapi",
    "uvicorn",
    "httpx",
    "requests",
    "ollama",
    "faster_whisper",
    "piper",
    "sqlite3",
}

CORE = pathlib.Path(__file__).resolve().parents[1] / "src" / "opic" / "core"


def imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_never_imports_infrastructure():
    offenders: dict[str, set[str]] = {}
    for path in sorted(CORE.rglob("*.py")):
        bad = imported_roots(path) & FORBIDDEN
        if bad:
            offenders[path.name] = bad
    assert offenders == {}


def test_the_purity_guard_actually_reads_the_core_modules():
    modules = {path.name for path in CORE.rglob("*.py")}
    assert {
        "rubric.py",
        "survey.py",
        "selfassess.py",
        "questions.py",
        "metrics.py",
        "scoring.py",
    } <= modules
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/core/test_core_end_to_end.py tests/test_core_purity.py -v`
Expected: both PASS if Tasks 2 through 7 are complete and clean. If either
fails, the failure is a real defect in an earlier task — fix it there, not here.
This is the one task whose tests are a gate rather than a driver.

- [ ] **Step 3: Write the README**

Create or replace `README.md`:

````markdown
# OPIc Simulator

로컬에서 실행되는 OPIc 말하기 시험 시뮬레이터. Runs entirely on your machine —
no audio or transcript ever leaves the computer.

## Status

Phase 1 complete: the pure scoring and exam-planning engine under
`src/opic/core/`. Adapters, web interface and report come next.

## Development

```bash
uv run --extra dev pytest
```

## Documents

- Design: `docs/superpowers/specs/2026-08-19-opic-simulator-design.md`
- Plan: `docs/superpowers/plans/2026-08-19-core-engine.md`
````

- [ ] **Step 4: Run the whole suite**

Run: `uv run --extra dev pytest -v`
Expected: PASS, every test from Tasks 1 through 8.

- [ ] **Step 5: Commit**

```bash
git add tests/core/test_core_end_to_end.py tests/test_core_purity.py README.md
git commit -m "test(core): cover the full engine path and guard core purity"
```

---

## What comes next

Phase 1 ends here with a library that plans an exam and scores it. The
following phases each get their own plan, written once this one lands:

- **Phase 2 — Adapters.** Install Ollama; wrap Qwen3, faster-whisper and Piper
  behind narrow interfaces. Verify two things empirically before building on
  them: that Qwen3 writes acceptable Korean, and that Whisper does not silently
  repair the speaker's grammar.
- **Phase 3 — Web.** FastAPI serving the five steps, microphone capture, TTS
  playback.
- **Phase 4 — Deferred evaluation.** Background pipeline with the 채점 중 progress
  screen over a WebSocket.
- **Phase 5 — Report.** The Korean-language score report with evidence.
