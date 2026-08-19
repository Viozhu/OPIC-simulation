# Question-writing time measurement (2026-08-19)

The Phase 3 web spec puts a 준비 중 ("preparing") screen between Setup and the
exam itself, sized to absorb `OllamaClient.write()` — the single call that
generates all fifteen exam questions before the test-taker sees the first one.
No prior note had timed `write()`; `2026-08-19-rater-model.md` only timed
`rate()`, which is a different call shape (one JSON object with five scored
dimensions and evidence quotes, per answer) from `write()` (one JSON array of
fifteen short question strings, one call for the whole exam).

## Method

A `SurveyAnswers` with `occupation=BUSINESS`, `is_student=False`,
`housing=ALONE`, `recent_course=LANGUAGE`, and twelve `selected_item_ids`:

```
movies, clubbing, live_shows, concerts, museums, parks,        # 6 leisure
listening_music, cooking,                                      # 2 hobby
yoga, walking,                                                  # 2 sport
domestic_travel, overseas_travel                                # 2 travel
```

verified against `SURVEY_ITEMS` and satisfying `GROUP_MINIMUMS` (leisure≥2,
hobby≥1, sport≥1, travel≥1) and `MIN_TOTAL_ITEMS=12`.
`build_blueprint(answers, self_assess_level=4, seed=7)` laid out the fixed
fifteen-slot (`EXAM_LENGTH`) exam shape once; `OllamaClient().write(answers,
blueprint)` — default `qwen3:14b`, the pinned model, at the project's real
`OLLAMA_TIMEOUT_S` (600s) — was then called three times in the same process,
each call timed independently with `time.monotonic()`. Ollama was already
running (`OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0`), same server as
the rater measurement.

Test: `tests/adapters/test_writer_timing.py::test_write_full_question_set_timing`,
marked `@pytest.mark.models` (excluded from the default suite).

## Results

| Trial | Elapsed (s) |
|---|---|
| 0 | 40.3 |
| 1 | 27.4 |
| 2 | 29.6 |

Mean: **32.4s**. All three calls returned exactly fifteen questions
(`len(questions) == EXAM_LENGTH`); no retries, no schema failures.

## Conclusion

The mean (32.4s) is well under the 150s threshold. **Setup y Sample cubren la
generación; la pantalla 준비 중 será rara.**

## Surprising

`write()` is roughly an order of magnitude faster than `rate()`
(32.4s mean vs. 253s mean per call, from `2026-08-19-rater-model.md`) despite
`write()` producing more total output — fifteen questions in one call versus
one five-dimension rating. Two likely reasons, neither isolated here:
`write()`'s schema is a flat array of short strings, much cheaper to
grammar-constrain than `rate()`'s nested five-object array with free-text
Korean commentary and verbatim evidence quotes; and `write()` runs once per
exam while `rate()` runs once per answer (up to fifteen times), so the
per-exam generation cost the 준비 중 screen has to cover is small in absolute
terms even though the total rating cost across a whole exam (Task 9's later
concern, not this one) is not.
