# OPIc Simulator

로컬에서 실행되는 OPIc 말하기 시험 시뮬레이터. Runs entirely on your machine —
no audio or transcript ever leaves the computer.

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

Needs Ollama running (`ollama serve`) and macOS for `say`. The first run
downloads the Whisper model.

**One server process.** Evaluation runs in a worker thread inside it; two
uvicorn workers would be two queues competing for one model. Do not pass
`--workers`.

Grading an exam takes about 75 minutes of machine time on an M2. Answers are
queued as you record them, so the wait after the last question is roughly half
of that. Closing the tab does not stop it, and restarting the server resumes
where it left off. An acceptance run on 2026-08-20 took a full fifteen-question
exam end to end — first question to graded report — in 71 minutes wall clock
on an M2, all 15 answers scored, which lines up with the 75-minute figure:
most of the grading happens in the background while you are still talking.

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

- **The rater's `correction_en` field is unreliable.** On a real graded exam,
  roughly a quarter of the corrections came back as an English *description*
  of the mistake rather than the sentence the candidate should have said. A
  fix to the rating prompt is in flight on a separate branch, not yet merged.
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
  - The retry layers multiply. `OllamaClient.rate` retries once inside
    `Worker._attempt`'s three, so a hung Ollama costs 30 minutes per answer.
