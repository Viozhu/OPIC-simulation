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
