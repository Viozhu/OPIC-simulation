# Phase 2, Plan B — Adapters and the Command-Line Exam

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the pure engine to the three local models and run a complete
OPIc exam end to end from the command line.

**Architecture:** Four ports declared in `core/ports.py` as `Protocol`, four
implementations in `src/opic/adapters/`. `core/` keeps importing nothing from
FastAPI, Ollama, Whisper or sqlite3, and the existing purity test still enforces
that. Adapter tests run against a committed real-speech fixture; only a handful
of tests load an actual model, and those are excluded by default.

**Tech Stack:** Python 3.13, uv, pytest, faster-whisper, Ollama over HTTP
(stdlib `urllib`, no HTTP dependency), macOS `say` and `ffmpeg` as subprocesses.

**Spec:** `docs/superpowers/specs/2026-08-19-phase-2-adapters-design.md` (sections 6, 6 bis, 7, 7.1, 7.2)

## Global Constraints

- Python 3.13. Project managed with `uv`. Run tests with `uv run --extra dev pytest`.
- `src/opic/core/` must not import `fastapi`, `httpx`, `requests`, `ollama`,
  `faster_whisper`, `piper`, or `sqlite3`. `tests/test_core_purity.py` enforces this.
  Adapters are free to import what they need.
- Import style: every module starts with `from __future__ import annotations`.
- All dataclasses in `core/` are `@dataclass(frozen=True, slots=True)`. Collections
  they hold are tuples, never lists.
- ACTFL scale, in this exact order: NL, NM, NH, IL, IM1, IM2, IM3, IH, AL.
- Whisper runs `medium`, `int8`, with `condition_on_previous_text=False`,
  `temperature=0.0`, `word_timestamps=True`.
- **The VAD contract is not negotiable:** `min_silence_duration_ms=250` and
  `speech_pad_ms=0`. faster-whisper's defaults (2000 / 400) reproduce the broken
  metrics this project already fixed once.
- TTS is macOS `say` with the voice `Samantha`, converted to 16 kHz mono by `ffmpeg`.
- Every quote the rater returns must appear verbatim in the transcript; quotes that
  do not are discarded.
- Korean user-facing strings end in `_ko`; English exam content ends in `_en`.
- Determinism: never iterate a set or an unordered dict where output order depends on it.
- Commit after every task. The default suite must be green before each commit.

## Measurements this plan is built on

Taken on the committed fixture (`evidence/sample-answer.wav`, 90 s of unscripted
non-native English) on an Apple M2:

| What | Value |
|---|---|
| VAD with faster-whisper defaults | 2 spans → `pause_ratio` 0.0235, `mean_utterance_length` 75.0 |
| VAD with the contract (250 / 0) | 24 spans, 22 merged → `pause_ratio` 0.2319, `mean_utterance_length` 6.8 |
| Whisper `medium` warm | 48 s per 90 s of audio |
| Qwen3 14B | 2.8 tok/s |
| Qwen3 8B | 5.3 tok/s, but ignored a five-item instruction without a forced schema |
| macOS `say` | 0.9 s for a 2 s sentence |

## Files

| File | Responsibility | Task |
|---|---|---|
| `src/opic/core/scoring.py` | MODIFY. `AnswerAssessment` carries its `Question` and `Transcript` | 1 |
| `src/opic/core/ports.py` | NEW. The four Protocols the adapters implement | 2 |
| `src/opic/adapters/config.py` | NEW. Every model id and tuning value, in one place | 3 |
| `src/opic/adapters/tts.py` | NEW. macOS `say` plus a content-addressed cache | 3 |
| `src/opic/adapters/stt.py` | NEW. faster-whisper with the VAD contract | 4 |
| `src/opic/adapters/llm.py` | NEW. Ollama: writes the questions, rates the answers | 5 |
| `src/opic/cli.py` | NEW. The end-to-end exam runner | 8 |
| `pyproject.toml` | MODIFY. faster-whisper dependency, `models` marker | 3 |

## A gap in the spec, and the ruling on it

Section 6 of the spec names three ports — `TextToSpeech`, `SpeechToText`, `Rater`
— but something has to produce the English wording of the fifteen questions, and
the Phase 1 spec (section 6) requires that wording to exist *before* the exam
starts. No port covers it.

This plan adds a fourth, `QuestionWriter`, alongside the other three. It is the
smallest change that closes the gap: the alternative, folding question generation
into `Rater`, would give one port two unrelated jobs and force the CLI to hold a
rater before it has anything to rate.

---

### Task 1: An assessment carries its question and its transcript

`AnswerAssessment` holds only `question_index`, so the report layer cannot show
what was asked, and `Evidence.quote` cannot be checked against what was said
without threading a parallel dictionary next to an object that calls itself
immutable.

**Files:**
- Modify: `src/opic/core/scoring.py`
- Modify: `tests/core/test_scoring.py`
- Modify: `tests/core/test_core_end_to_end.py`

**Interfaces:**
- Consumes: `Question` from `opic.core.questions`, `Transcript` from `opic.core.transcript`.
- Produces:
  - `AnswerAssessment(question: Question, transcript: Transcript,
    dimension_scores: tuple[DimensionScore, ...], metrics: AnswerMetrics)`
    with `question_index` now a read-only property returning `question.slot.index`.
  - `level_for` unchanged.

Replacing the stored `question_index` with a derived property keeps `aggregate`
working unchanged — it reads `a.question_index` and will keep reading it — while
removing the chance of an index that disagrees with the question it names.

- [ ] **Step 1: Write the failing test**

In `tests/core/test_scoring.py`, extend the imports so they include:

```python
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.transcript import Span, Transcript, Word
```

Replace the whole `assessment` helper with this pair:

```python
def transcript_for(text: str = "I usually go to the beach on weekends") -> Transcript:
    spoken = text.split()
    return Transcript(
        text=text,
        words=tuple(
            Word(w, i * 0.4, i * 0.4 + 0.3, 0.9) for i, w in enumerate(spoken)
        ),
        speech_spans=(Span(0.0, len(spoken) * 0.4),),
        duration_s=60.0,
    )


def assessment(
    index: int,
    levels: dict[Dimension, ActflLevel],
    mean_confidence: float = 0.9,
    low_rate: float = 0.1,
) -> AnswerAssessment:
    return AnswerAssessment(
        question=Question(
            slot=slot(index, QuestionType.DESCRIPTION, "movies"),
            text_en="Tell me about the last movie you saw.",
        ),
        transcript=transcript_for(),
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
```

Then append:

```python
def test_an_assessment_knows_its_question_and_what_was_said():
    a = assessment(3, flat(ActflLevel.IM2))
    assert a.question_index == 3
    assert a.question.text_en.endswith("?") or a.question.text_en.endswith(".")
    assert "beach" in a.transcript.text


def test_question_index_follows_the_question_and_cannot_drift():
    a = assessment(3, flat(ActflLevel.IM2))
    assert a.question_index == a.question.slot.index
    with pytest.raises(Exception):
        a.question_index = 9
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/core/test_scoring.py -v`
Expected: FAIL — `AnswerAssessment.__init__() got an unexpected keyword argument 'question'`.

- [ ] **Step 3: Write the implementation**

In `src/opic/core/scoring.py`, add to the imports:

```python
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.transcript import Transcript
```

(`QuestionSlot` and `QuestionType` are already imported; add only what is missing.)

Replace the `AnswerAssessment` dataclass with:

```python
@dataclass(frozen=True, slots=True)
class AnswerAssessment:
    """One answer, judged — together with what was asked and what was said.

    The report quotes the question, and every piece of evidence has to be
    checkable against the transcript it came from. Holding both here is what
    keeps the result object self-contained instead of something the caller has
    to carry side tables for.
    """

    question: Question
    transcript: Transcript
    dimension_scores: tuple[DimensionScore, ...]
    metrics: AnswerMetrics

    @property
    def question_index(self) -> int:
        return self.question.slot.index

    def level_for(self, dimension: Dimension) -> ActflLevel:
        for score in self.dimension_scores:
            if score.dimension is dimension:
                return score.level
        raise ValueError(
            f"answer {self.question_index} has no score for {dimension.value}"
        )
```

- [ ] **Step 4: Fix the end-to-end test**

In `tests/core/test_core_end_to_end.py`, extend the import from
`opic.core.questions` to include `Question`, and replace the
`AnswerAssessment(...)` construction inside the list comprehension so it reads:

```python
        AnswerAssessment(
            question=Question(slot=slot, text_en="Tell me about that."),
            transcript=Transcript(
                text=" ".join(spoken),
                words=words,
                speech_spans=(Span(0.0, 3.1), Span(5.0, 8.0)),
                duration_s=30.0,
            ),
            dimension_scores=tuple(
```

leaving the rest of the comprehension exactly as it is.

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opic/core/scoring.py tests/core/test_scoring.py tests/core/test_core_end_to_end.py
git commit -m "feat(core): an assessment carries its question and transcript"
```

---

### Task 2: The ports

**Files:**
- Create: `src/opic/core/ports.py`
- Test: `tests/core/test_ports.py`
- Modify: `tests/test_core_purity.py`

**Interfaces:**
- Consumes: `Question`, `QuestionSlot` from `opic.core.questions`; `Transcript`
  from `opic.core.transcript`; `AnswerMetrics` from `opic.core.metrics`;
  `DimensionScore` from `opic.core.scoring`; `SurveyAnswers` from `opic.core.survey`.
- Produces four runtime-checkable Protocols: `TextToSpeech`, `SpeechToText`,
  `QuestionWriter`, `Rater`.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_ports.py`:

```python
from __future__ import annotations

from pathlib import Path

from opic.core.metrics import AnswerMetrics
from opic.core.ports import QuestionWriter, Rater, SpeechToText, TextToSpeech
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.rubric import ActflLevel
from opic.core.survey import SurveyAnswers
from opic.core.transcript import Transcript


class FakeTts:
    def synthesize(self, text: str) -> Path:
        return Path("/tmp/fake.wav")


class FakeStt:
    def transcribe(self, audio: Path) -> Transcript:
        return Transcript(text="", words=(), speech_spans=(), duration_s=1.0)


class FakeWriter:
    def write(
        self, answers: SurveyAnswers, blueprint: tuple[QuestionSlot, ...]
    ) -> tuple[Question, ...]:
        return ()


class FakeRater:
    def rate(
        self,
        question: Question,
        transcript: Transcript,
        metrics: AnswerMetrics,
    ) -> tuple:
        return ()


class NotATts:
    def speak(self, text: str) -> Path:
        return Path("/tmp/nope.wav")


def test_a_conforming_object_satisfies_its_port():
    assert isinstance(FakeTts(), TextToSpeech)
    assert isinstance(FakeStt(), SpeechToText)
    assert isinstance(FakeWriter(), QuestionWriter)
    assert isinstance(FakeRater(), Rater)


def test_an_object_with_the_wrong_method_does_not():
    assert not isinstance(NotATts(), TextToSpeech)


def test_the_ports_module_imports_nothing_from_the_adapters():
    import opic.core.ports as ports

    source = Path(ports.__file__).read_text(encoding="utf-8")
    assert "opic.adapters" not in source
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/core/test_ports.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.core.ports'`.

- [ ] **Step 3: Write the implementation**

Create `src/opic/core/ports.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot
from opic.core.scoring import DimensionScore
from opic.core.survey import SurveyAnswers
from opic.core.transcript import Transcript


@runtime_checkable
class TextToSpeech(Protocol):
    """Turns a question's English text into an audio file."""

    def synthesize(self, text: str) -> Path: ...


@runtime_checkable
class SpeechToText(Protocol):
    """Turns a recorded answer into a transcript with timings and speech spans."""

    def transcribe(self, audio: Path) -> Transcript: ...


@runtime_checkable
class QuestionWriter(Protocol):
    """Writes the English wording for every slot in a blueprint.

    The whole set is produced before the exam begins, so no question ever waits
    on a language model while the candidate is sitting in front of it.
    """

    def write(
        self, answers: SurveyAnswers, blueprint: tuple[QuestionSlot, ...]
    ) -> tuple[Question, ...]: ...


@runtime_checkable
class Rater(Protocol):
    """Judges one answer along every scoring dimension."""

    def rate(
        self,
        question: Question,
        transcript: Transcript,
        metrics: AnswerMetrics,
    ) -> tuple[DimensionScore, ...]: ...
```

Declaring these in `core/` is what keeps the dependency pointing inward: the
engine states what it needs, and the adapters conform to it.

- [ ] **Step 4: Extend the purity guard**

In `tests/test_core_purity.py`, add `"ports.py"` to the set inside
`test_the_purity_guard_actually_reads_the_core_modules`.

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opic/core/ports.py tests/core/test_ports.py tests/test_core_purity.py
git commit -m "feat(core): declare the four adapter ports"
```

---

### Task 3: Configuration and the text-to-speech adapter

**Files:**
- Create: `src/opic/adapters/__init__.py` (empty)
- Create: `src/opic/adapters/config.py`
- Create: `src/opic/adapters/tts.py`
- Modify: `pyproject.toml`
- Test: `tests/adapters/__init__.py` (empty), `tests/adapters/test_tts.py`

**Interfaces:**
- Consumes: nothing from earlier tasks except the `TextToSpeech` port's shape.
- Produces:
  - `config` module holding `SAY_VOICE`, `TTS_SAMPLE_RATE`, `WHISPER_MODEL`,
    `WHISPER_COMPUTE_TYPE`, `VAD_MIN_SILENCE_MS`, `VAD_SPEECH_PAD_MS`,
    `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_S`.
  - `cache_path(text: str, voice: str, cache_dir: Path) -> Path` — pure, content
    addressed.
  - `SayTextToSpeech(cache_dir: Path, voice: str = config.SAY_VOICE)` with
    `synthesize(text: str) -> Path`.

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/__init__.py` as an empty file, then `tests/adapters/test_tts.py`:

```python
from __future__ import annotations

import wave
from pathlib import Path

import pytest

from opic.adapters import config
from opic.adapters.tts import SayTextToSpeech, cache_path
from opic.core.ports import TextToSpeech


def test_the_adapter_satisfies_the_port(tmp_path):
    assert isinstance(SayTextToSpeech(cache_dir=tmp_path), TextToSpeech)


def test_the_cache_path_is_content_addressed(tmp_path):
    a = cache_path("hello there", "Samantha", tmp_path)
    b = cache_path("hello there", "Samantha", tmp_path)
    c = cache_path("hello THERE", "Samantha", tmp_path)
    assert a == b
    assert a != c
    assert a.suffix == ".wav"
    assert a.parent == tmp_path


def test_a_different_voice_is_a_different_cache_entry(tmp_path):
    assert cache_path("hello", "Samantha", tmp_path) != cache_path(
        "hello", "Alex", tmp_path
    )


def test_a_cached_file_is_returned_without_synthesising(tmp_path):
    voice = "Samantha"
    text = "already here"
    target = cache_path(text, voice, tmp_path)
    target.write_bytes(b"not really a wav")

    calls: list[str] = []

    def explode(*args, **kwargs):
        calls.append("ran")
        raise AssertionError("synthesis must not run for a cached entry")

    tts = SayTextToSpeech(cache_dir=tmp_path, voice=voice, runner=explode)
    assert tts.synthesize(text) == target
    assert calls == []


def test_an_empty_text_is_refused(tmp_path):
    with pytest.raises(ValueError):
        SayTextToSpeech(cache_dir=tmp_path).synthesize("   ")


@pytest.mark.models
def test_real_synthesis_produces_mono_16k_audio(tmp_path):
    out = SayTextToSpeech(cache_dir=tmp_path).synthesize(
        "Tell me about a memorable trip you took."
    )
    assert out.exists()
    with wave.open(str(out)) as wf:
        assert wf.getframerate() == config.TTS_SAMPLE_RATE
        assert wf.getnchannels() == 1
        assert wf.getnframes() / wf.getframerate() > 1.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/adapters/test_tts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.adapters'`.

- [ ] **Step 3: Write the configuration module**

Create `src/opic/adapters/__init__.py` as an empty file, then
`src/opic/adapters/config.py`:

```python
from __future__ import annotations

# Text to speech. macOS `say`, because piper-tts ships an espeak-ng binary with
# the build machine's data path compiled into it and fails at import.
SAY_VOICE = "Samantha"
TTS_SAMPLE_RATE = 16000

# Speech to text.
WHISPER_MODEL = "medium"
WHISPER_COMPUTE_TYPE = "int8"

# The voice-activity contract. faster-whisper's defaults are 2000 and 400, under
# which no silence below about 1.2s can exist, the 0.5s merge threshold in
# core/metrics.py never fires, and pause_ratio collapses to 0.02 with
# mean_utterance_length at 75 — the exact numbers that made those metrics
# useless. Measured on evidence/sample-answer.wav; with the values below the
# same recording yields pause_ratio 0.23 and mean_utterance_length 6.8.
VAD_MIN_SILENCE_MS = 250
VAD_SPEECH_PAD_MS = 0

# The rater. Qwen3 8B runs at 5.3 tok/s on an M2 against 2.8 for the 14B, but
# needs a forced JSON schema to answer every dimension.
OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3:8b"
OLLAMA_TIMEOUT_S = 600
```

- [ ] **Step 4: Write the adapter**

Create `src/opic/adapters/tts.py`:

```python
from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path

from opic.adapters import config


def cache_path(text: str, voice: str, cache_dir: Path) -> Path:
    """Where this exact wording, in this exact voice, is cached.

    Content addressed, so a question repeated across sessions is synthesised
    once and never again.
    """
    digest = hashlib.sha256(f"{voice}\n{text}".encode()).hexdigest()
    return cache_dir / f"{digest}.wav"


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)


class SayTextToSpeech:
    """Speaks a question using macOS `say`, resampled by ffmpeg.

    `runner` exists so tests can prove the cache short-circuits synthesis
    without shelling out.
    """

    def __init__(
        self,
        cache_dir: Path,
        voice: str = config.SAY_VOICE,
        runner: Callable[[list[str]], None] = _run,
    ) -> None:
        self._cache_dir = cache_dir
        self._voice = voice
        self._run = runner

    def synthesize(self, text: str) -> Path:
        if not text.strip():
            raise ValueError("cannot synthesise empty text")

        target = cache_path(text, self._voice, self._cache_dir)
        if target.exists():
            return target

        self._cache_dir.mkdir(parents=True, exist_ok=True)
        raw = target.with_suffix(".aiff")
        self._run(["say", "-v", self._voice, "-o", str(raw), text])
        self._run(
            [
                "ffmpeg", "-v", "error", "-y",
                "-i", str(raw),
                "-ar", str(config.TTS_SAMPLE_RATE),
                "-ac", "1",
                str(target),
            ]
        )
        raw.unlink(missing_ok=True)
        return target
```

- [ ] **Step 5: Register the dependency and the marker**

In `pyproject.toml`, change the `dependencies` line to:

```toml
dependencies = ["faster-whisper>=1.2"]
```

and replace the `[tool.pytest.ini_options]` block with:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
markers = [
    "models: needs a real local model (Ollama, Whisper) or macOS `say`; excluded by default",
]
addopts = "-m 'not models'"
```

- [ ] **Step 6: Run the suite, then the model-marked test on its own**

Run: `uv run --extra dev pytest`
Expected: PASS, with the `models`-marked test deselected.

Run: `uv run --extra dev pytest -m models tests/adapters/test_tts.py -v`
Expected: PASS — this one actually calls `say` and `ffmpeg`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/opic/adapters tests/adapters
git commit -m "feat(adapters): synthesise questions with macOS say"
```

---

### Task 4: The speech-to-text adapter and its VAD contract

**Files:**
- Create: `src/opic/adapters/stt.py`
- Test: `tests/adapters/test_stt.py`

**Interfaces:**
- Consumes: `Span`, `Transcript`, `Word` from `opic.core.transcript`; `config`.
- Produces:
  - `spans_from_timestamps(timestamps: list[dict], sampling_rate: int) -> tuple[Span, ...]`
  - `WhisperSpeechToText(model_size=config.WHISPER_MODEL, compute_type=config.WHISPER_COMPUTE_TYPE)`
    with `transcribe(audio: Path) -> Transcript`.

`faster_whisper.vad.get_speech_timestamps` returns dicts with `start` and `end`
in **samples**, not seconds. Dividing by the sampling rate is the whole of
`spans_from_timestamps`, and getting it wrong silently scales every pause by
16000.

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/test_stt.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from opic.adapters import config
from opic.adapters.stt import WhisperSpeechToText, spans_from_timestamps
from opic.core.metrics import compute_metrics, merge_spans
from opic.core.ports import SpeechToText
from opic.core.transcript import Span, Transcript, Word

FIXTURE_AUDIO = Path("evidence/sample-answer.wav")
FIXTURE_JSON = Path("evidence/sample-transcript.json")


def test_the_adapter_satisfies_the_port():
    assert isinstance(WhisperSpeechToText(), SpeechToText)


def test_timestamps_in_samples_become_spans_in_seconds():
    spans = spans_from_timestamps(
        [{"start": 0, "end": 16000}, {"start": 32000, "end": 48000}],
        sampling_rate=16000,
    )
    assert spans == (Span(0.0, 1.0), Span(2.0, 3.0))


def test_no_speech_detected_gives_no_spans():
    assert spans_from_timestamps([], sampling_rate=16000) == ()


def test_the_vad_contract_is_pinned_to_the_measured_values():
    assert config.VAD_MIN_SILENCE_MS == 250
    assert config.VAD_SPEECH_PAD_MS == 0


@pytest.mark.models
def test_the_contract_produces_usable_metrics_on_real_speech():
    """The defaults give pause_ratio 0.0235 and mean_utterance_length 75.0 on this
    recording — the broken numbers. The contract gives 0.23 and 6.8."""
    from faster_whisper import vad
    from faster_whisper.audio import decode_audio

    pcm = decode_audio(str(FIXTURE_AUDIO), sampling_rate=16000)
    options = vad.VadOptions(
        min_silence_duration_ms=config.VAD_MIN_SILENCE_MS,
        speech_pad_ms=config.VAD_SPEECH_PAD_MS,
    )
    spans = spans_from_timestamps(
        vad.get_speech_timestamps(pcm, options, sampling_rate=16000),
        sampling_rate=16000,
    )
    assert len(spans) > 10
    assert len(merge_spans(spans)) > 10

    words = tuple(
        Word(w["text"], w["start"], w["end"], w["probability"])
        for w in json.loads(FIXTURE_JSON.read_text())["configs"]["mitigated"]["words"]
    )
    m = compute_metrics(
        Transcript(
            text="",
            words=words,
            speech_spans=spans,
            duration_s=len(pcm) / 16000,
        )
    )
    assert 0.15 < m.pause_ratio < 0.35
    assert 4.0 < m.mean_utterance_length < 12.0


@pytest.mark.models
def test_real_transcription_preserves_the_speakers_errors():
    result = WhisperSpeechToText().transcribe(FIXTURE_AUDIO)
    assert result.words
    assert result.speech_spans
    assert result.duration_s == pytest.approx(90.0, abs=1.0)
    lowered = result.text.lower()
    assert "a island" in lowered or "we take a bath" in lowered
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/adapters/test_stt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.adapters.stt'`.

- [ ] **Step 3: Write the implementation**

Create `src/opic/adapters/stt.py`:

```python
from __future__ import annotations

from pathlib import Path

from opic.adapters import config
from opic.core.transcript import Span, Transcript, Word

SAMPLING_RATE = 16000


def spans_from_timestamps(
    timestamps: list[dict],
    sampling_rate: int = SAMPLING_RATE,
) -> tuple[Span, ...]:
    """Convert voice-activity timestamps from samples into seconds."""
    return tuple(
        Span(t["start"] / sampling_rate, t["end"] / sampling_rate) for t in timestamps
    )


class WhisperSpeechToText:
    """faster-whisper, tuned so it does not repair the speaker's grammar.

    `condition_on_previous_text=False` and `temperature=0.0` are what keep the
    errors in: with the defaults the model inserts elided subjects and rewrites
    tense, deleting roughly five real mistakes per ninety seconds.

    The VAD options come from config and are load-bearing — see the note there.
    """

    def __init__(
        self,
        model_size: str = config.WHISPER_MODEL,
        compute_type: str = config.WHISPER_COMPUTE_TYPE,
    ) -> None:
        self._model_size = model_size
        self._compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._model_size, device="cpu", compute_type=self._compute_type
            )
        return self._model

    def transcribe(self, audio: Path) -> Transcript:
        from faster_whisper import vad
        from faster_whisper.audio import decode_audio

        model = self._load()
        segments, info = model.transcribe(
            str(audio),
            language="en",
            word_timestamps=True,
            condition_on_previous_text=False,
            temperature=0.0,
        )

        text_parts: list[str] = []
        words: list[Word] = []
        for segment in segments:
            text_parts.append(segment.text)
            for w in segment.words or ():
                words.append(Word(w.word, w.start, w.end, w.probability))

        pcm = decode_audio(str(audio), sampling_rate=SAMPLING_RATE)
        options = vad.VadOptions(
            min_silence_duration_ms=config.VAD_MIN_SILENCE_MS,
            speech_pad_ms=config.VAD_SPEECH_PAD_MS,
        )
        spans = spans_from_timestamps(
            vad.get_speech_timestamps(pcm, options, sampling_rate=SAMPLING_RATE),
            sampling_rate=SAMPLING_RATE,
        )

        return Transcript(
            text="".join(text_parts).strip(),
            words=tuple(words),
            speech_spans=spans,
            duration_s=info.duration,
        )
```

The VAD runs separately from the transcription rather than through
`vad_filter=True`, because the filtered path does not hand back the speech
timestamps and those spans are exactly what the metrics need.

- [ ] **Step 4: Run the default suite, then the model-marked tests**

Run: `uv run --extra dev pytest`
Expected: PASS, with the two `models` tests deselected.

Run: `uv run --extra dev pytest -m models tests/adapters/test_stt.py -v`
Expected: PASS. The transcription test loads the `medium` model and takes about
a minute on first run.

- [ ] **Step 5: Commit**

```bash
git add src/opic/adapters/stt.py tests/adapters/test_stt.py
git commit -m "feat(adapters): transcribe with the voice-activity contract"
```

---

### Task 5: The Ollama adapter

**Files:**
- Create: `src/opic/adapters/llm.py`
- Test: `tests/adapters/test_llm.py`

**Interfaces:**
- Consumes: `Question`, `QuestionSlot`, `QuestionType` from `opic.core.questions`;
  `Transcript` from `opic.core.transcript`; `AnswerMetrics` from `opic.core.metrics`;
  `DimensionScore`, `Evidence` from `opic.core.scoring`; `ActflLevel`, `Dimension`
  from `opic.core.rubric`; `SurveyAnswers`, `ITEMS_BY_ID` from `opic.core.survey`.
- Produces:
  - `RATING_SCHEMA` and `QUESTIONS_SCHEMA` — JSON schemas handed to Ollama's
    `format` field.
  - `parse_rating(payload: dict, transcript_text: str) -> tuple[DimensionScore, ...]`
    — pure, and the place where invented quotes are dropped.
  - `OllamaClient(url=config.OLLAMA_URL, model=config.OLLAMA_MODEL)` implementing
    both `write(...)` and `rate(...)`.

A local model will occasionally quote something the candidate never said.
`parse_rating` discards any evidence whose `quote` is not a substring of the
transcript, because a fabricated quote is worse than no evidence at all.

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/test_llm.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from opic.adapters.llm import (
    QUESTIONS_SCHEMA,
    RATING_SCHEMA,
    OllamaClient,
    parse_rating,
)
from opic.core.ports import QuestionWriter, Rater
from opic.core.rubric import ActflLevel, Dimension

SAID = "I go to the beach and we take a bath there"


def payload(dimension="grammar", level="IM2", quote="we take a bath"):
    return {
        "dimensions": [
            {
                "dimension": dimension,
                "level": level,
                "comment_ko": "문법 오류가 있습니다.",
                "evidence": [
                    {
                        "quote": quote,
                        "issue_ko": "시제가 잘못되었습니다.",
                        "correction_en": "we took a bath",
                    }
                ],
            }
        ]
    }


def test_the_client_satisfies_both_ports():
    client = OllamaClient()
    assert isinstance(client, Rater)
    assert isinstance(client, QuestionWriter)


def test_a_rating_becomes_dimension_scores():
    scores = parse_rating(payload(), SAID)
    assert len(scores) == 1
    assert scores[0].dimension is Dimension.GRAMMAR
    assert scores[0].level is ActflLevel.IM2
    assert scores[0].comment_ko
    assert scores[0].evidence[0].correction_en == "we took a bath"


def test_an_invented_quote_is_discarded():
    scores = parse_rating(payload(quote="I climbed Mount Everest"), SAID)
    assert scores[0].evidence == ()


def test_a_real_quote_survives_alongside_an_invented_one():
    p = payload()
    p["dimensions"][0]["evidence"].append(
        {"quote": "never said this", "issue_ko": "x", "correction_en": "y"}
    )
    scores = parse_rating(p, SAID)
    assert len(scores[0].evidence) == 1
    assert scores[0].evidence[0].quote == "we take a bath"


def test_an_unknown_dimension_is_refused():
    with pytest.raises(ValueError):
        parse_rating(payload(dimension="charisma"), SAID)


def test_an_unknown_level_is_refused():
    with pytest.raises(ValueError):
        parse_rating(payload(level="SUPERB"), SAID)


def test_the_rating_schema_demands_every_dimension():
    dims = RATING_SCHEMA["properties"]["dimensions"]
    assert dims["minItems"] == len(Dimension)
    assert dims["maxItems"] == len(Dimension)
    allowed = dims["items"]["properties"]["dimension"]["enum"]
    assert set(allowed) == {d.value for d in Dimension}


def test_the_questions_schema_asks_for_strings():
    assert QUESTIONS_SCHEMA["properties"]["questions"]["items"]["type"] == "string"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/adapters/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.adapters.llm'`.

- [ ] **Step 3: Write the implementation**

Create `src/opic/adapters/llm.py`:

```python
from __future__ import annotations

import json
import urllib.request
from typing import Any

from opic.adapters import config
from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import DimensionScore, Evidence
from opic.core.survey import ITEMS_BY_ID, SurveyAnswers
from opic.core.transcript import Transcript

RATING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "dimensions": {
            "type": "array",
            "minItems": len(Dimension),
            "maxItems": len(Dimension),
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {
                        "type": "string",
                        "enum": [d.value for d in Dimension],
                    },
                    "level": {
                        "type": "string",
                        "enum": [level.name for level in ActflLevel],
                    },
                    "comment_ko": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "quote": {"type": "string"},
                                "issue_ko": {"type": "string"},
                                "correction_en": {"type": "string"},
                            },
                            "required": ["quote", "issue_ko", "correction_en"],
                        },
                    },
                },
                "required": ["dimension", "level", "comment_ko", "evidence"],
            },
        }
    },
    "required": ["dimensions"],
}

QUESTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["questions"],
}

_TYPE_BRIEF: dict[QuestionType, str] = {
    QuestionType.SELF_INTRO: "ask the candidate to introduce themselves",
    QuestionType.DESCRIPTION: "ask them to describe their {topic}",
    QuestionType.HABIT: "ask what they normally do regarding {topic}",
    QuestionType.EXPERIENCE: "ask about a specific past experience with {topic}",
    QuestionType.ROLEPLAY_SETUP: "set up a role-play situation about {topic}",
    QuestionType.ROLEPLAY_FOLLOWUP: "continue that role-play about {topic}",
}


def parse_rating(payload: dict, transcript_text: str) -> tuple[DimensionScore, ...]:
    """Turn the model's JSON into scores, dropping quotes it invented.

    A local model will occasionally attribute words to the candidate that they
    never said. Evidence that cannot be found in the transcript is discarded
    rather than shown: a fabricated quote is worse than none.
    """
    scores: list[DimensionScore] = []
    for item in payload["dimensions"]:
        try:
            dimension = Dimension(item["dimension"])
        except ValueError as exc:
            raise ValueError(f"unknown dimension {item['dimension']!r}") from exc
        try:
            level = ActflLevel[item["level"]]
        except KeyError as exc:
            raise ValueError(f"unknown level {item['level']!r}") from exc

        evidence = tuple(
            Evidence(
                quote=e["quote"],
                issue_ko=e["issue_ko"],
                correction_en=e["correction_en"],
            )
            for e in item.get("evidence", ())
            if e["quote"] in transcript_text
        )
        scores.append(
            DimensionScore(
                dimension=dimension,
                level=level,
                comment_ko=item["comment_ko"],
                evidence=evidence,
            )
        )
    return tuple(scores)


class OllamaClient:
    """Writes the exam's questions and rates its answers, over Ollama's HTTP API.

    Uses `urllib` rather than an HTTP library so the project keeps exactly one
    runtime dependency.
    """

    def __init__(
        self,
        url: str = config.OLLAMA_URL,
        model: str = config.OLLAMA_MODEL,
        timeout_s: int = config.OLLAMA_TIMEOUT_S,
    ) -> None:
        self._url = url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s

    def _generate(self, prompt: str, schema: dict[str, Any]) -> dict:
        body = json.dumps(
            {
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0.2},
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
            return json.loads(json.loads(response.read())["response"])

    def write(
        self, answers: SurveyAnswers, blueprint: tuple[QuestionSlot, ...]
    ) -> tuple[Question, ...]:
        lines = []
        for slot in blueprint:
            topic = (
                ITEMS_BY_ID[slot.topic_id].label_en if slot.topic_id else "themselves"
            )
            brief = _TYPE_BRIEF[slot.qtype].format(topic=topic)
            lines.append(f"{slot.index + 1}. {brief}, at {slot.target.name} level")

        prompt = (
            "You are writing questions for an OPIc English speaking test.\n"
            "Write one spoken-English question for each item below. Each must be "
            "one or two sentences, natural, and answerable in 90 seconds.\n"
            "Return them in order, exactly one per item.\n\n"
            + "\n".join(lines)
        )
        payload = self._generate(prompt, QUESTIONS_SCHEMA)
        texts = payload["questions"]
        if len(texts) != len(blueprint):
            raise ValueError(
                f"model returned {len(texts)} questions for {len(blueprint)} slots"
            )
        return tuple(
            Question(slot=slot, text_en=text.strip())
            for slot, text in zip(blueprint, texts, strict=True)
        )

    def rate(
        self,
        question: Question,
        transcript: Transcript,
        metrics: AnswerMetrics,
    ) -> tuple[DimensionScore, ...]:
        prompt = (
            "You are an OPIc rater. Evaluate ONE spoken answer.\n\n"
            f"QUESTION (type: {question.slot.qtype.value}): {question.text_en}\n\n"
            "TRANSCRIPT (verbatim, errors preserved — do NOT assume typos):\n"
            f"{transcript.text}\n\n"
            "OBJECTIVE METRICS (already computed — never recompute or invent these):\n"
            f"words_per_minute: {metrics.words_per_minute:.0f}\n"
            f"pause_ratio: {metrics.pause_ratio:.2f}\n"
            f"mean_utterance_length: {metrics.mean_utterance_length:.1f}\n"
            f"type_token_ratio: {metrics.type_token_ratio:.2f}\n\n"
            "Rate every dimension. comment_ko and issue_ko MUST be natural Korean. "
            "Every quote MUST appear verbatim in the transcript. Keep each comment "
            "to one sentence and give at most one piece of evidence per dimension."
        )
        return parse_rating(self._generate(prompt, RATING_SCHEMA), transcript.text)
```

- [ ] **Step 4: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/opic/adapters/llm.py tests/adapters/test_llm.py
git commit -m "feat(adapters): write and rate through Ollama"
```

---

### Task 6: Decide whether the filler metrics survive

`filler_count` and `filler_rate` read zero on real speech because Whisper strips
disfluencies. The spec says to try recovering them by biasing the decoder before
deleting the metrics.

**Files:**
- Create: `docs/superpowers/notes/2026-08-19-filler-recovery.md`
- Modify, ONLY if the experiment succeeds: `src/opic/adapters/config.py`,
  `src/opic/adapters/stt.py`, `tests/adapters/test_stt.py`
- Modify, ONLY if the experiment fails: `src/opic/core/metrics.py`,
  `tests/core/test_metrics.py`, `src/opic/adapters/llm.py`

**Interfaces:**
- Consumes: `WhisperSpeechToText` from Task 4.
- Produces: either `config.WHISPER_INITIAL_PROMPT` (on success) or an
  `AnswerMetrics` without the two filler fields (on failure).

- [ ] **Step 1: Run the experiment**

Write and run a throwaway script — do not commit it — that transcribes
`evidence/sample-answer.wav` three times with `WhisperModel("medium",
device="cpu", compute_type="int8")`, `language="en"`,
`condition_on_previous_text=False`, `temperature=0.0`, `word_timestamps=True`,
and these three values of `initial_prompt`:

1. `None`
2. `"Um, uh, so, like, you know, I mean..."`
3. `"Uh... um... er... so uh... I mean, uh..."`

For each run, print the full transcript and count how many words normalise into
`opic.core.metrics.FILLERS`.

- [ ] **Step 2: Write down what happened**

Create `docs/superpowers/notes/2026-08-19-filler-recovery.md` recording, for each
of the three runs: the exact `initial_prompt`, the filler count, and the first
200 characters of the transcript. State the verdict in one sentence at the top.

The threshold, decided before looking: the experiment **succeeds** if any prompt
yields three or more fillers without visibly degrading the transcript — no new
repeated words, no dropped content compared with run 1.

- [ ] **Step 3a: If it succeeded — pin the prompt**

Add to `src/opic/adapters/config.py`:

```python
# Whisper strips disfluencies unless the decoder is biased toward them. This
# prompt is what makes filler_count mean anything; see
# docs/superpowers/notes/2026-08-19-filler-recovery.md for the measurement.
WHISPER_INITIAL_PROMPT = "<the winning prompt, verbatim>"
```

In `src/opic/adapters/stt.py`, add `initial_prompt=config.WHISPER_INITIAL_PROMPT,`
to the `model.transcribe(...)` call.

Append to `tests/adapters/test_stt.py`:

```python
@pytest.mark.models
def test_the_initial_prompt_recovers_hesitation_markers():
    from opic.core.metrics import FILLERS, _normalise

    result = WhisperSpeechToText().transcribe(FIXTURE_AUDIO)
    fillers = sum(1 for w in result.words if _normalise(w.text) in FILLERS)
    assert fillers >= 3
```

- [ ] **Step 3b: If it failed — remove the metrics**

In `src/opic/core/metrics.py`: delete the `FILLERS` frozenset and its comment,
delete the `filler_count` and `filler_rate` fields from `AnswerMetrics`, delete
the `fillers = sum(...)` line, and delete both fields from the two
`AnswerMetrics(...)` constructions.

In `tests/core/test_metrics.py`: delete
`test_fillers_are_counted_case_insensitively_and_without_punctuation` and
`test_common_words_that_are_not_hesitations_are_not_fillers`, and remove the two
filler assertions from `test_empty_speech_yields_zeroed_metrics` if present.

In `tests/core/test_scoring.py`: remove `filler_count=3,` and `filler_rate=0.025,`
from the `metrics()` helper.

In `src/opic/adapters/llm.py`: nothing to change — the rating prompt never
mentioned fillers.

Add to `docs/superpowers/notes/2026-08-19-filler-recovery.md`, at the end:

```markdown
## Consequence

`filler_count` and `filler_rate` were removed from `AnswerMetrics`. A field that
always reads zero misrepresents what the system measures. If a future
speech-to-text engine preserves disfluencies, they come back with it.
```

- [ ] **Step 4: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

On success:

```bash
git add docs/superpowers/notes src/opic/adapters/config.py src/opic/adapters/stt.py tests/adapters/test_stt.py
git commit -m "feat(adapters): bias whisper toward disfluencies"
```

On failure:

```bash
git add docs/superpowers/notes src/opic/core/metrics.py tests/core/test_metrics.py tests/core/test_scoring.py
git commit -m "refactor(core): drop the filler metrics whisper cannot feed"
```

---

### Task 7: Choose the rating model on evidence

The spec fixes the decision criteria in advance: five valid five-dimension
responses out of five attempts, every quote present in the transcript, and
Korean the user judges comparable to the 14B's.

**Files:**
- Create: `docs/superpowers/notes/2026-08-19-rater-model.md`
- Modify, if 8B fails: `src/opic/adapters/config.py`

**Interfaces:**
- Consumes: `OllamaClient` from Task 5, `WhisperSpeechToText` from Task 4.
- Produces: a pinned `config.OLLAMA_MODEL` with the measurement behind it.

- [ ] **Step 1: Run both models five times each**

Write and run a throwaway script — do not commit it — that builds one
`Question` (type `EXPERIENCE`, text
`"Tell me about a memorable trip you took. Where did you go, who were you with, and what happened that made it memorable?"`),
loads the `mitigated` transcript from `evidence/sample-transcript.json` into a
`Transcript`, computes its metrics, then calls `OllamaClient(model=...).rate(...)`
five times for `qwen3:8b` and five times for `qwen3:14b`.

Record per call: wall-clock seconds, how many dimensions came back, how many
evidence items survived `parse_rating`, and how many were discarded as invented.

- [ ] **Step 2: Write down what happened**

Create `docs/superpowers/notes/2026-08-19-rater-model.md` with a table of those
ten runs, plus one full Korean rating from each model quoted in full so the
difference is legible without re-running anything.

- [ ] **Step 3: Ask the user to judge the Korean**

Show the user both quoted ratings and ask which reads as natural, technically
accurate Korean. This is the one criterion no test can settle. Wait for the
answer.

- [ ] **Step 4: Pin the decision**

If the 8B met all three criteria, `config.OLLAMA_MODEL` already says `qwen3:8b`
and nothing changes. Otherwise set it to `qwen3:14b`.

Either way, append to the note:

```markdown
## Decision

Pinned `OLLAMA_MODEL = "<model>"`. Estimated evaluation time for a full
fifteen-question exam: <N> minutes of rating plus about twelve minutes of
transcription.
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/notes/2026-08-19-rater-model.md src/opic/adapters/config.py
git commit -m "docs: pin the rating model on measured evidence"
```

---

### Task 8: The command-line exam

**Files:**
- Create: `src/opic/cli.py`
- Test: `tests/test_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `record_answer(path: Path, seconds: int, runner=...) -> Path`
  - `run_exam(answers: SurveyAnswers, self_assess_level: int, seed: int,
    session_dir: Path, tts, stt, writer, rater, recorder=..., player=...) -> ExamResult`
  - `main(argv: list[str] | None = None) -> int`

`run_exam` takes every collaborator as an argument, so the test drives the whole
flow with fakes and never touches a model or a microphone.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from opic.cli import run_exam
from opic.core.metrics import AnswerMetrics
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opic.cli'`.

- [ ] **Step 3: Write the implementation**

Create `src/opic/cli.py`:

```python
from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from opic.adapters import config
from opic.adapters.llm import OllamaClient
from opic.adapters.stt import WhisperSpeechToText
from opic.adapters.tts import SayTextToSpeech
from opic.core.metrics import compute_metrics
from opic.core.questions import build_blueprint
from opic.core.scoring import AnswerAssessment, ExamResult, aggregate
from opic.core.survey import (
    Housing,
    Occupation,
    RecentCourse,
    SurveyAnswers,
    validate_survey,
)

ANSWER_SECONDS = 90


def record_answer(
    path: Path,
    seconds: int = ANSWER_SECONDS,
    device: str = ":0",
) -> Path:
    """Capture one spoken answer from the microphone via ffmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "avfoundation", "-i", device,
            "-t", str(seconds),
            "-ar", "16000", "-ac", "1",
            str(path),
        ],
        check=True,
    )
    return path


def play(path: Path) -> None:
    subprocess.run(["afplay", str(path)], check=True)


def run_exam(
    answers: SurveyAnswers,
    self_assess_level: int,
    seed: int,
    session_dir: Path,
    tts,
    stt,
    writer,
    rater,
    recorder: Callable[[Path, int], Path] = record_answer,
    player: Callable[[Path], None] = play,
) -> ExamResult:
    """Run a whole exam: ask, record, transcribe, judge, aggregate, save.

    Every collaborator is an argument so the flow can be exercised without a
    microphone or a model.
    """
    issues = validate_survey(answers)
    if issues:
        detail = ", ".join(f"{i.error.value}({i.detail})" for i in issues)
        raise ValueError(f"invalid survey: {detail}")

    session_dir.mkdir(parents=True, exist_ok=True)
    blueprint = build_blueprint(answers, self_assess_level, seed)
    questions = writer.write(answers, blueprint)

    recordings: list[Path] = []
    for question in questions:
        player(tts.synthesize(question.text_en))
        recordings.append(
            recorder(session_dir / f"answer-{question.slot.index:02d}.wav", ANSWER_SECONDS)
        )

    assessments: list[AnswerAssessment] = []
    for question, recording in zip(questions, recordings, strict=True):
        transcript = stt.transcribe(recording)
        metrics = compute_metrics(transcript)
        assessments.append(
            AnswerAssessment(
                question=question,
                transcript=transcript,
                dimension_scores=rater.rate(question, transcript, metrics),
                metrics=metrics,
            )
        )

    result = aggregate(blueprint, assessments)
    (session_dir / "result.json").write_text(
        json.dumps(_as_json(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _as_json(result: ExamResult) -> dict:
    return {
        "final_level": result.final_level.name,
        "dimensions": {d.value: level.name for d, level in result.dimension_levels},
        "by_type": {t.value: level.name for t, level in result.by_type},
        "by_topic": {topic: level.name for topic, level in result.by_topic},
        "pronunciation": {
            "mean_confidence": result.pronunciation.mean_confidence,
            "low_confidence_rate": result.pronunciation.low_confidence_rate,
            "indicative": result.pronunciation.indicative,
        },
        "answers": [
            {
                "index": a.question_index,
                "question_en": a.question.text_en,
                "transcript": a.transcript.text,
                "words_per_minute": a.metrics.words_per_minute,
                "pause_ratio": a.metrics.pause_ratio,
                "scores": [
                    {
                        "dimension": s.dimension.value,
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
                    for s in a.dimension_scores
                ],
            }
            for a in result.assessments
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opic", description="Run a local OPIc mock exam")
    parser.add_argument("--survey", type=Path, required=True, help="survey answers as JSON")
    parser.add_argument("--level", type=int, required=True, choices=range(1, 7))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--session", type=Path, default=Path("data/sessions/latest"))
    args = parser.parse_args(argv)

    raw = json.loads(args.survey.read_text(encoding="utf-8"))
    answers = SurveyAnswers(
        occupation=Occupation(raw["occupation"]),
        is_student=raw["is_student"],
        housing=Housing(raw["housing"]),
        selected_item_ids=tuple(raw["selected_item_ids"]),
        recent_course=(
            RecentCourse(raw["recent_course"]) if raw.get("recent_course") else None
        ),
    )

    client = OllamaClient()
    result = run_exam(
        answers=answers,
        self_assess_level=args.level,
        seed=args.seed,
        session_dir=args.session,
        tts=SayTextToSpeech(cache_dir=Path("data/tts_cache")),
        stt=WhisperSpeechToText(),
        writer=client,
        rater=client,
    )
    print(f"\n최종 등급: {result.final_level.name}")
    print(f"결과 파일: {args.session / 'result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the full suite**

Run: `uv run --extra dev pytest`
Expected: PASS.

- [ ] **Step 5: Update the README**

Replace the `## Status` section of `README.md` with:

```markdown
## Status

Phase 1 and Phase 2 complete: the pure engine, the local adapters, and a full
exam runnable from the command line.

```bash
uv run python -m opic.cli --survey my-survey.json --level 4
```

Needs Ollama running (`ollama serve`) and macOS for `say`. The first run
downloads the Whisper model.
```

- [ ] **Step 6: Commit**

```bash
git add src/opic/cli.py tests/test_cli.py README.md
git commit -m "feat: run a whole exam from the command line"
```

---

## What Phase 3 picks up

The web interface: the five steps in a browser, microphone capture through
`MediaRecorder`, and the 채점 중 screen. That screen has to be designed as a
background job the candidate returns to — the measurements above put a full
evaluation somewhere between twenty-five and thirty-five minutes.
