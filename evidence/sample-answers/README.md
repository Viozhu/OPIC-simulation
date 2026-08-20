# sample-answers

Fifteen `answer-NN.json` files copied from a real, fully graded OPIc exam
session (`data/sessions/20260820-105109/`), run on 2026-08-20. Real speech,
transcribed by faster-whisper; real judgements, produced by qwen3:14b. The
exam's final level was IH.

Only the per-answer files are copied here — not `result.json` from the same
session. `result.json` is fully derivable from these fifteen files via
`opic.session.assessments.aggregate_available` (or plain
`opic.core.scoring.aggregate`, since this is a complete fifteen-answer run),
so keeping a second, separately-copied aggregate would just be a stale
snapshot waiting to diverge from the code that computes it.

Kept as a fixture so the report tests run against what the models actually
emit, not against invented data — including a case a hand-written fixture
would not have had: `answer-00.json`'s `fluency` dimension carries two
evidence items even though the judging prompt asks for at most one.
