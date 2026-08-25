# Phase 5 — plan

Design: `../specs/2026-08-24-phase-5-report-page-design.md`.

Each task is committable on its own and leaves the suite green. Tasks 1–3 make
the page real without any model call; 4–6 add the judged sections; 7 wires it
to the exam.

## 1. Words reach the report model

`core/report.py`: `AnswerReport` gains `transcript_words: tuple[Word, ...]`,
filled from the assessment. `report_json` in `session/assessments.py` untouched
— `done.js` reads what it already read.

Test: the real-fixture report carries the same word count per answer as the
assessment it came from, and an unscored answer carries none.

## 2. The narrative model

`core/narrative.py`: frozen dataclasses `PatternItem`, `ErrorPattern`,
`GapSection`, `Caveat`, `AnswerRewrite`, `Narrative`. One function,
`quotes_in_report(report) -> frozenset[str]`, which the adapter's parse uses to
reject a quote the rater never produced.

`core/ports.py`: `NarrativeWriter` protocol.

Test: `quotes_in_report` collects every evidence quote across dimensions and
answers, including an answer carrying two items for one dimension.

## 3. The page

`core/page.py`: `render_html(report, narrative, meta) -> str`, plus `PAGE_CSS`
as a module constant and `Meta` (session id, seed, spoken minutes, self-assessed
level). Ported from the hand-written page: same tokens, same components, both
theme blocks, the ladder, the distribution, the wpm chart, the splits, the
table, and the per-answer blocks with low-confidence words marked.

`narrative=None` renders the derived page alone.

Tests (`tests/core/test_page.py`), against the real fixture:
- fifteen answer blocks, and each transcript round-trips once the markup is
  stripped — the page never alters what was said
- every low-confidence word in the fixture is marked, and no other word is
- HTML-escaping: an apostrophe in a question survives as text, not markup
- `narrative=None` omits the judged sections and still closes every tag
- a narrative with an `invented` rewrite renders the warning; without it, not
- light and dark tokens both defined; no `<script>`

## 4. Prompts and schemas

`adapters/narrative.py`: `ANALYSIS_SCHEMA`, `REWRITES_SCHEMA`,
`analysis_prompt(report)`, `rewrites_prompt(report)`, and
`parse_analysis` / `parse_rewrites`, which enforce the two guards.

Tests (`tests/adapters/test_narrative.py`):
- a pattern item quoting something absent from the report is rejected
- a rewrite naming an answer that does not exist, or a second rewrite for an
  answer already covered, is dropped
- a short set is kept, not rejected: the page renders a rewrite where it has
  one and the question and transcript alone where it does not, so thirteen good
  rewrites are worth thirteen good rewrites
- `invented` defaults to true when absent, never to false
- the prompts name every answer index and carry the transcripts

## 5. The Anthropic path

`write_narrative` on `AnthropicClient`: two `_generate` calls through the
existing structured-output path, each parsed by task 4, each retried once.
A failure in the analysis call still returns the rewrites, and the reverse.

Test: a fake client returning canned payloads produces a `Narrative`; one
returning a bad analysis and a good rewrite set produces a `Narrative` with no
analysis and fifteen rewrites.

## 6. Writing the file

`session/pages.py`: `write(root, session_id, html) -> Path`, atomic via
`.tmp` + `replace`, and `page_path` in `store.py` (`report-ko.html`).

Test: the file lands, is valid UTF-8, and a second write replaces it without
leaving a `.tmp` behind.

## 7. Wiring

`session/worker.py` `_aggregate`: after `result.json` lands, build the report,
ask for a narrative, render, write. Wrapped so that nothing here can lose an
exam that is already graded — a failed narrative call, a failed render and a
failed write are all logged and swallowed.

`cli.py`: `opic report <session-id> [--no-llm] [--force]`, which rebuilds from
`result.json` on disk. Refuses an existing file without `--force`.

Tests: the worker writes a page for a graded session with a stub writer that
raises, and the exam still ends; the CLI command regenerates a session and
`--no-llm` makes no model call.

## 8. Documentation

`README.md` gains the command. `tests/test_core_purity.py` gains `page.py` and
`narrative.py` in the expected module set.
