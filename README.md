# OPIc Simulator

로컬에서 실행되는 OPIc 말하기 시험 시뮬레이터. Runs entirely on your machine —
no audio or transcript ever leaves the computer.

## Status

Phases 1 to 3 complete: the pure engine, the local adapters, and a browser
interface that runs a whole exam and grades it while you take it.

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
where it left off.

The command-line exam still works:

```bash
uv run python -m opic.cli --survey my-survey.json --level 4
```

Start from `examples/survey.json`.

## Development

```bash
uv run --extra dev pytest
```

## Documents

- Design: `docs/superpowers/specs/2026-08-19-opic-simulator-design.md`
- Plan: `docs/superpowers/plans/2026-08-19-core-engine.md`

---

## What comes next

Phases 1 to 3 are done: the pure engine, the local adapters, and the browser
interface — including deferred evaluation in a background worker with a 채점 중
progress screen, folded into Phase 3 rather than staying a phase of its own.

- **Phase 4 — Report.** A readable, Korean-language score report: the
  per-dimension breakdown, quoted evidence for each score, and the
  pronunciation proxy the pipeline already computes but does not yet show.
