# Phase 5 — the report page, generated every exam

## What exists

`data/sessions/20260821-140338/report-ko.handwritten.html` is a standalone
Korean report for one real exam, written by hand. It is the page the candidate
actually reads: verdict, the five dimensions against the whole ACTFL scale,
where the 75 assessments landed, the fifteen grammar corrections clustered into
named patterns, the weakest question type, the measured speech numbers, a table
of all fifteen answers, every question with its transcript, and an AL-level
rewrite of each answer.

Nothing regenerates it. The next exam produces `result.json` and the in-app
`done.js` screen, and that is all.

## What this phase does

Every finished exam writes `report-ko.html` into its own session directory,
with the structure of the hand-written page. A CLI command regenerates it for
any session, including sessions graded before this phase existed.

## The split that decides the design

Reading the hand-written page against `result.json` separates it cleanly.

**Derived — no model call.** Masthead, verdict and ladder, the five dimension
rows with the `comment_ko` the rater already wrote, the distribution of the 75
assessments, by-type and by-topic splits, the words-per-minute chart, the
measured stats, the fifteen-answer table, and every question with its
transcript and its low-confidence words marked. About seventy per cent of the
page, and all of it a second reading of data that is already on disk.

**Judged — needs a model call.** Which named patterns the fifteen corrections
fall into, the prose that says what a number means, which question type is the
biggest hole, and the fifteen AL rewrites. None of it is derivable: it is
reading, and a template that tried to fake it would produce sentences that are
true of every exam and useful for none.

So: a pure renderer that always works, plus an optional `Narrative` it renders
when one is available. `OPIC_LLM=ollama`, a missing key, a refused request or a
schema violation all end the same way — the derived page, whole, with the judged
sections absent rather than empty.

## The two guards

Both come from the same lesson as the rater's correction field: a schema
constrains where a prompt only asks.

**Quotes are grouped, never written.** The pattern sections quote the
candidate. Every `quote` and `correction_en` the model returns must match an
evidence item already in `result.json`, byte for byte, or the narrative is
rejected. The model's job is to name and group what the rater found, and it
cannot introduce a sentence she never said.

**An invented episode is labelled as one.** Two of the fifteen questions asked
for a specific past experience and got a description of a routine, so there is
no episode in the transcript to rewrite. Writing one means inventing it. The
hand-written page did exactly that — a leg-press Saturday, a moving-day
dinner — and unlabelled, in a study document, that is someone else's memory
presented as the candidate's own.

The schema therefore requires `invented: bool` on every rewrite, and the
renderer marks a rewrite that carries it: this situation is an example, replace
it with something that happened to you. The prompt is told to prefer real
material and to set the flag honestly when it cannot.

## Shape

    core/narrative.py    Narrative, ErrorPattern, PatternItem, GapSection,
                         Caveat, AnswerRewrite — data only, plus the quote
                         check. No prompts, no transport.
    core/ports.py        NarrativeWriter — one method, report + answers in,
                         Narrative out.
    core/page.py         render_html(report, narrative | None, meta) -> str.
                         The stylesheet is a module constant; core reads no
                         files. Third renderer of the same Report model that
                         render_text and done.js already render, so no
                         scoring decision is made here.
    adapters/narrative.py    Prompts, JSON schemas, and the parse that
                         enforces both guards. Shared, the way llm.py is.
    adapters/anthropic_llm.py    write_narrative on AnthropicClient, through
                         the same _generate as questions and ratings.
    session/pages.py     Writes the file, atomically, next to result.json.

`AnswerReport` gains `transcript_words` so the page can mark low-confidence
words inline. `report.unclear` stays as it is: it answers a different question
(which words does the recogniser doubt across the whole exam) and is capped at
ten.

Two model calls, not one: the analysis and the fifteen rewrites are independent,
and a single tool call carrying both is a single point of truncation. A failure
in either leaves the other's sections intact.

## Ollama

Not implemented. The local rater returns one level for every answer of a real
exam (`docs/superpowers/notes/2026-08-19-rater-model.md`, and the constant IH
×75 measured since); a narrative from the same model is not worth the ninety
minutes it would take. `OPIC_LLM=ollama` gets the derived page.

## Cost

Two Haiku calls per exam, against fifteen minutes of speaking and fifteen
grading calls that already happened. The exam is the expensive part.

## What running it changed

Three things the design above did not predict, all measured against the real
session `20260821-140338`.

**The Messages API rejects size and length bounds.** `output_config.format.
schema` came back with `400 … For 'array' type, property 'maxItems' is not
supported`. The bounds now come off in `anthropic_llm.strict()`, beside the
`additionalProperties` it already added, and the shared schemas keep them for
the local backend. Nothing was lost: every bound they expressed is one the
parser enforces on the way back in, for both backends.

**`invented` had to cover added facts, not just invented episodes.** The first
run produced a self-introduction that called the candidate a housewife. She
never said what she does. The flag was true only for made-up episodes, so that
came through as faithful. The prompt now forbids adding any fact about her life
that is not somewhere in the transcripts, and `invented` means "contains
anything she did not say" — episode or detail. The warning on the page says the
same.

**A general instruction did not survive fifteen answers.** Told once, in the
preamble, that a question asking for a specific past experience must be
rewritten as an episode, the model narrated one for answer 09 and kept the
routine framing for answer 06 — in the same response, and differently on the
next run. The demand is now attached to the answers it applies to, in the exam
sheet itself, matched on the question wording (`asks_for_an_episode`). With
that, all four episode questions came back as episodes.

The third one generalises: a per-item instruction the model reads next to the
item beats the same instruction stated once for the batch.

## Not in scope

Translating the page. Publishing it anywhere. Changing the in-app `done.js`
screen, which already shows question and transcript per answer. Comparing two
exams over time.
