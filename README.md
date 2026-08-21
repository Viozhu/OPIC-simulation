# OPIc Simulator

OPIc 말하기 시험 시뮬레이터. Your recordings never leave the computer: the
microphone, Whisper and `say` are all local, and no audio is ever uploaded.

**The grading is not local by default.** Since the rater moved to Claude, the
*transcript* of each answer — the text Whisper produced, not the audio — is sent
to the Anthropic API, together with the question and the objective metrics. Set
`OPIC_LLM=ollama` to keep everything on the machine; see **The rater** below.

## Status

Phases 1 to 4 complete: the pure engine, the local adapters, a browser
interface that runs a whole exam and grades it while you take it, and a
report that explains the grade. The report shows the level, a per-dimension
breakdown with the candidate's own quoted mistakes and the English
correction for each, an explanation when a weak dimension capped the grade,
the words the recogniser could not catch clearly, breakdowns by question
type and topic, and an answer-by-answer detail. The same report prints from
the CLI.

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
schema and the same filter.

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

---

## What comes next

Phases 1 to 4 are done: the pure engine, the local adapters, the browser
interface — including deferred evaluation in a background worker with a 채점 중
progress screen, folded into Phase 3 rather than staying a phase of its own —
and the report. What's left is not a phase, it's a punch list:

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
