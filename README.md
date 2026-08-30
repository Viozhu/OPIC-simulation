# OPIc Simulator

OPIc 말하기 시험 시뮬레이터. Your recordings never leave the computer: the
microphone, Whisper and `say` are all local, and no audio is ever uploaded.

**The grading is not local by default.** Since the rater moved to Claude, the
*transcript* of each answer — the text Whisper produced, not the audio — is sent
to the Anthropic API, together with the question and the objective metrics. Set
`OPIC_LLM=ollama` to keep everything on the machine; see **The rater** below.

## Status

Phases 1 to 5 complete: the pure engine, the local adapters, a browser
interface that runs a whole exam and grades it while you take it, and a
report that explains the grade. The report shows the level, a per-dimension
breakdown with the candidate's own quoted mistakes and the English
correction for each, an explanation when a weak dimension capped the grade,
the words the recogniser could not catch clearly, breakdowns by question
type and topic, and an answer-by-answer detail. It closes on a recap: the
findings restated in one screen, and the arithmetic that produced the band —
the per-dimension medians, the weighted mean and what it rounded to, whether
the advanced set raised it, and whether a weak dimension capped it. That
closing section is derived, so it is there with no model and no key. The same
report prints from the CLI.

Every finished exam also writes `report-ko.html` into its own session folder:
a standalone page the candidate can keep, open in any browser and hand to a
teacher. It carries everything above plus, when the Anthropic backend is in
use, the parts a template cannot write — the corrections grouped into named
patterns, the weakest question type shown with the answers that made the case,
each answer rewritten at AL with a note on what changed, and, beside the
closing arithmetic, a read of why the band is that band and not the one above
it. A rewrite that
contains anything the candidate did not actually say is labelled as such on
the page.

Rebuild it for any graded session, including ones graded before this existed:

```bash
uv run python -m opic.cli --report data/sessions/20260821-140338
uv run python -m opic.cli --report data/sessions/... --no-llm   # derived sections only
uv run python -m opic.cli --report data/sessions/... --force    # overwrite
```

`--no-llm` needs no key, no network and no cost: it renders only what is
derived from `result.json`. The same happens by itself on `OPIC_LLM=ollama`,
or when the model call fails — the page is written either way, with the judged
sections absent rather than faked.

```bash
uv run python -m opic.cli --serve      # http://localhost:8000
```

Needs macOS for `say` and an Anthropic API key (or `OPIC_LLM=ollama` and
`ollama serve`). The first run downloads the Whisper model.

### The rater

One object writes the questions and grades the answers, and two adapters
implement it. `OPIC_LLM` picks between them:

| `OPIC_LLM` | Model | Notes |
| --- | --- | --- |
| `anthropic` (default) | `claude-haiku-4-5` | Needs a key. Grades in seconds per answer. |
| `ollama` | `qwen3:14b` | Needs `ollama serve`. Nothing leaves the machine. |

The key is read from `API_KEY_ANTHROPIC` or `ANTHROPIC_API_KEY`, from the
environment or from a `.env` in the repo root (git-ignored; an exported variable
wins over the file). An `ant auth login` profile works too.

```bash
echo 'API_KEY_ANTHROPIC=sk-ant-...' > .env
```

The switch exists because the local rater stopped discriminating: on a real
fifteen-question exam `qwen3:14b` returned the same level — IH — for every
single answer, which is a constant and not a grade. `tools/rater_bench.py` puts
both raters side by side on the same answers, through the same prompt, the same
schema and the same filter. `tools/rater_calibration.py` adds
the column neither of them has — see **Calibration** below.

Run on 2026-08-21 over the 15 stored answers of that exam
(`data/sessions/20260820-145223`):

| | `qwen3:14b` | `claude-haiku-4-5` |
| --- | --- | --- |
| Levels emitted, 15 answers × 5 dimensions | `IH` ×75 | IM1 32, IM2 31, IH 6, IL 4, NH 2 |
| Answers graded at more than one level | 0 / 15 | 15 / 15 |
| Quotes discarded as not in the transcript | — | 0 / 70 |
| Corrections sharing under a quarter of their quote | 2 / 69 | 4 / 70 |
| Wall clock | ~75 min | 102 s (7 s per answer) |
| Cost at list price | — | $0.09 |

Two things that table does not say. There is no ground truth here, so a rater
that moves is not thereby a rater that is right — only one that is no longer a
constant. And 63 of Haiku's 75 verdicts are IM1 or IM2, so most of its
discrimination happens inside a two-band window; the mean gap to the local
rater is 2.45 bands, which is Haiku grading this candidate consistently lower,
not the two raters disagreeing about who is good at what.

### How strict is it?

Candidates reported the grade felt strict. It was, and the cause was in three
places, none of them the rater's opinion of anyone's English.

The prompt carried no scale. `rating_prompt` named nine levels through the
schema's enum and defined none of them, so the rater supplied the scale from
its own prior and settled in the middle of it: across the three real graded
exams in `data/sessions`, 171 of 225 verdicts — 76% — were IM1 or IM2. The
prompt now carries `LEVEL_DESCRIPTORS`, condensed from the ACTFL Proficiency
Guidelines 2024, together with the rule ACTFL actually rates on: the band is
the one the sample *sustains*, not the one it touches once. It also says that
IM1/IM2/IM3 are thirds of ACTFL's single Intermediate Mid rather than three
major bands, which is what made the middle of the scale wide enough to hide in.

The aggregation rounded down, twice. `_weighted_rank` took `math.floor` of the
weighted mean, so 4.85 — five sixths of the way from IM1 to IM2 — was reported
as IM1; two of the three real exams lost a whole band exactly there. And an
even count of answers took the *lower* of the two middle bands, which a
fifteen-question exam never sees but the by-type and by-topic breakdowns hit
constantly, so the table explaining the grade was stricter than the grade. Both
now round to the nearest band, ties up. Re-aggregating the stored verdicts with
no re-grading moves two of five sessions from IM1 to IM2.

The weak-dimension cap in `_capped` is left alone. It has a basis the other two
did not — ACTFL requires performance sustained across *all* the criteria of a
level — and it should be judged against real grades rather than adjusted by
argument.

### Calibration

There is still no ground truth in this repository. `rater_bench.py` shows
whether two raters disagree; it cannot show which is right.
`tools/rater_calibration.py` is where that column goes:

```bash
uv run python tools/rater_calibration.py --labels labels.json
uv run python tools/rater_calibration.py --labels labels.json --regrade
```

`labels.json` maps a session id to the OPIc grade that session's candidate
actually holds. Without `--regrade` the stored verdicts are reused and the run
is free, which measures the aggregation; with it every answer is graded again
through the current prompt, which is the only thing a prompt change can be
measured by.

The headline is the mean *signed* gap in bands: negative means this simulator
grades below the real exam, and by how much. Agreement is printed twice, since
OPIc's nine bands are not ACTFL's — collapsing IM1/IM2/IM3 back into one IM is
what makes the figure comparable to ACTFL's own.

The bar is not 100%. ACTFL double-rates every operational OPIc, and its two
certified raters agree exactly 74% of the time on English, adjacent 25%, two or
more bands apart 1% (N=8017, 2012-2014). A rater at 74% has matched the humans.

Nothing has been calibrated yet: the labelled sessions have to exist first, and
ten is a floor rather than a target. ACTFL's own rated sample library sits
behind a terms-of-use gate and is marked proprietary, so the practical source
is candidates who hold a real OPIc grade and also sit a session here.

**One server process.** Evaluation runs in a worker thread inside it; two
uvicorn workers would be two queues over one sessions folder, each grading
answers the other already took. Do not pass `--workers`. (On the local backend
they would also be two queues fighting over one model.)

Answers are queued as you record them, so grading overlaps with the exam.
Closing the tab does not stop it, and restarting the server resumes where it
left off.

The timings below were all measured on `OPIC_LLM=ollama`, and no equivalent
acceptance run has been done on Haiku yet — the numbers stand as the local
baseline, not as what the default now does. Grading an exam took about 75
minutes of machine time on an M2. An acceptance run on 2026-08-20 took a full
fifteen-question exam end to end — first question to graded report — in 71
minutes wall clock, all 15 answers scored. Of that, 14 minutes were the exam and
57 were spent waiting after the last answer: grading ran at roughly five minutes
per answer and the queue could not keep up with a candidate who was still
talking.

The command-line exam still works, and prints the same report at the end:

```bash
uv run python -m opic.cli --survey my-survey.json --level 4
```

Start from `examples/survey.json`.

### The question voice

Candidates reported the questions as flat and robotic. Two separate things
cause that, and only one of them is code.

The cadence is code, and is fixed. `say` used to read a whole question as one
unbroken contour; it now takes a 300ms lead-in, a 600ms stop where the setup
ends and the question begins, and 400ms between sub-questions. Where those cuts
go was measured over the 105 questions in `data/sessions`: 22 have a second
sentence, 23 use an em-dash for the same beat, and the other 62 are one
sentence of up to 28 words with comma-separated sub-questions — so pausing only
at full stops would have reached a fifth of them.

The durations carry a trap worth knowing. `[[slnc N]]` does not add N
milliseconds; it *replaces* the pause the punctuation would have made. So there
is a floor, and under it the reading comes out faster and flatter than with no
marker at all. Measured at a comma, 95 wpm, holding everything else fixed:

| `[[slnc N]]` after a comma | Samantha | Ava (Premium) |
| --- | --- | --- |
| none | 2.866s | 2.805s |
| 50 | 2.692s (−174ms) | 2.735s (−70ms) |
| 150 | 2.808s (−58ms) | 2.851s (+46ms) |
| 200 | 2.866s (0) | 2.921s (+116ms) |
| 400 | 3.110s (+244ms) | 3.153s (+348ms) |
| 600 | 3.354s (+488ms) | 3.397s (+592ms) |

The floor belongs to the voice, not to `say`: 200ms for Samantha, about 115ms
for Ava. Re-measure it whenever `SAY_VOICE` changes — a value that cleared the
old voice's floor is not thereby audible in the new one. A test asserts the
defaults clear the higher of the two.

The timbre was the other half, and it is the voice. `SAY_VOICE` was Samantha, a
*compact* system voice — concatenative, one unbroken contour, flat by
construction. It is now `Ava (Premium)`, one of the neural voices macOS offers
as a free download under System Settings, Accessibility, Spoken Content, System
Voice, Manage Voices. They are not installed by default; until one is, `say -v
'?'` lists only the compact set. Nothing about the privacy story changes —
Premium voices synthesise on the machine like any other.

The full `Ava (Premium)` and not the bare `Ava` on purpose. Bare `Ava` resolves
to whichever Ava is installed, and would fall back to `Ava (Enhanced)` the
moment Premium were removed. The cache key stores the string, not the voice it
resolved to, so that fallback would be silent: questions already spoken would
keep their Premium audio and only new wordings would come back in the lesser
voice.

`SAY_RATE` did not survive the change intact either. Quantisation turned out to
be a property of the voice: Samantha ignored most of the number, with 115-140
producing one duration, 85-105 the next and 60-75 the next, and 95 was the
middle of three usable steps. Ava has no plateaus — every step from 60 to 175
changes the duration — and reads faster at the same number, taking 6.246s over
a question Samantha took 6.506s on. Matching the old pace exactly would mean
about 80. It is left at 95 because Ava is intelligible at a speed Samantha was
not.

Pick voice, speed and pauses by ear — there is no metric for robotic:

```bash
uv run python tools/voice_preview.py --session data/sessions/<id> --questions 3
uv run python tools/voice_preview.py --voices Samantha Ava --rates 95 115
uv run python tools/voice_preview.py --pauses 400 600 800 --clauses 0 400
```

Every change to the voice, the rate or a pause changes the cache key, so the
next exam resynthesises instead of quietly replaying the old audio. The old
entries under `data/tts_cache` are then dead weight and can be deleted.

## Development

```bash
uv run --extra dev pytest
```

## Documents

- Master design: `docs/superpowers/specs/2026-08-19-opic-simulator-design.md`
- Phase 1 plan: `docs/superpowers/plans/2026-08-19-core-engine.md`
- Phase 2 design: `docs/superpowers/specs/2026-08-19-phase-2-adapters-design.md`
- Phase 2 plans: `docs/superpowers/plans/2026-08-19-phase-2a-core-repairs.md`, `docs/superpowers/plans/2026-08-19-phase-2b-adapters.md`
- Phase 3 design: `docs/superpowers/specs/2026-08-19-phase-3-web-design.md`
- Phase 3 plan: `docs/superpowers/plans/2026-08-19-phase-3-web.md`
- Phase 4 design: `docs/superpowers/specs/2026-08-20-phase-4-report-design.md`
- Phase 4 plan: `docs/superpowers/plans/2026-08-20-phase-4-report.md`
- Phase 5 design: `docs/superpowers/specs/2026-08-24-phase-5-report-page-design.md`
- Phase 5 plan: `docs/superpowers/plans/2026-08-24-phase-5-report-page.md`

---

## What comes next

Phases 1 to 4 are done: the pure engine, the local adapters, the browser
interface — including deferred evaluation in a background worker with a 채점 중
progress screen, folded into Phase 3 rather than staying a phase of its own —
and the report. What's left is not a phase, it's a punch list:

- **Nothing is calibrated against a real OPIc grade.** The strictness in the
  aggregation was found by reading the code and confirmed by re-aggregating
  stored verdicts, which needs no ground truth. Whether the *rater* is strict,
  and whether the new band table fixed it, cannot be answered that way.
  `tools/rater_calibration.py` is ready and has never been run on real labels,
  because none exist yet.
- **No live exam has been taken on Haiku.** The bench has graded 15 real
  stored answers on it, so the cost and the wall clock are measured, but that
  path starts from `answer-NN.json` on disk. Nobody has yet sat down, spoken
  into the microphone and been graded by the default backend end to end.
- **The physical microphone is still unproven.** The acceptance run drove a
  real browser and a real `MediaRecorder`, but the audio came from a file fed
  through Chrome's fake audio device, so the path from an actual microphone
  to Whisper has never been exercised end to end.
- **Four items carried over from phase 3, still true:**
  - `FileResponse` trusts `audio_path` straight out of `session.json`, with
    no root containment — safe only as long as both start paths bind to
    `127.0.0.1` and there is one user.
  - `describe_issue_ko` parses `ValidationIssue.detail` with `str.partition`,
    so editing a `validate_survey` format string breaks survey submission,
    and reordering its fields yields a plausible Korean sentence with the
    numbers swapped.
  - A permanently failing `_generate` never marks a session failed: the
    candidate gets a timeout screen, and the operator gets a console
    traceback and nothing else.
  - The retry layers multiply. Both adapters' `rate` retries once inside
    `Worker._attempt`'s three, so a hung Ollama costs 30 minutes per answer.
    On the Anthropic path the SDK adds two more retries under that, so one
    answer can cost up to eighteen requests before it is given up on.
