# OPIc Simulator

로컬에서 실행되는 OPIc 말하기 시험 시뮬레이터. Runs entirely on your machine —
no audio or transcript ever leaves the computer.

## Status

Phase 1 and Phase 2 complete: the pure engine, the local adapters, and a full
exam runnable from the command line.

```bash
uv run python -m opic.cli --survey my-survey.json --level 4
```

Requires macOS (for `say`), `ffmpeg`, and Ollama running with the rating model
pulled:

```bash
ollama serve
ollama pull qwen3:14b
```

The first run also downloads the Whisper `medium` model.

**Budget about 100 minutes for a full exam:** roughly 25 minutes answering, then
about 12 minutes of transcription and an hour of rating. The rating model runs at
under 3 tokens per second on an M2, which is what dominates. Per-answer results
are written to the session directory as they complete, so a failure late in the
run does not discard the earlier ones.

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
