# Rater model measurement (2026-08-19)

**Decision criteria, fixed before measuring** (per the phase-2b task-7 brief):

1. Five valid five-dimension responses out of five attempts.
2. Every surviving quote present in the transcript, and the discard rate
   `parse_rating` reports (a high discard rate is itself a signal).
3. Korean quality comparable to the 14B's — no automated test can settle this.
   **Left to the reader**, per this task's controller. The pin below reflects
   only criteria 1 and 2.

## Method

One `Question` of type `EXPERIENCE` with the text
`"Tell me about a memorable trip you took. Where did you go, who were you with, and what happened that made it memorable?"`.
The `mitigated` transcript from `evidence/sample-transcript.json`, loaded into a
`Transcript` with `speech_spans` computed from `evidence/sample-answer.wav` via
the same faster-whisper VAD contract `WhisperSpeechToText` uses
(`VAD_MIN_SILENCE_MS=250`, `VAD_SPEECH_PAD_MS=0`), then
`opic.core.metrics.compute_metrics` for the objective metrics. `AnswerMetrics`
no longer carries filler fields (see `2026-08-19-filler-recovery.md`), so the
`Transcript` was built from real words/spans and metrics derived rather than
hand-constructed.

`OllamaClient(model=...).rate(question, transcript, metrics)` was called five
times against `qwen3:8b` and five times against `qwen3:14b`, using the
project's real `OLLAMA_TIMEOUT_S` (600s). Each call was a separate process
invocation so a hang or timeout could not lose earlier results. A call that
raised was recorded as a failed trial and not retried.

## Results

| Model | Trial | Result | Elapsed (s) | Dimensions returned | Evidence surviving | Evidence discarded |
|---|---|---|---|---|---|---|
| qwen3:8b | 0 | OK | 133.69 | 5 (**grammar duplicated, relevance missing** — see below) | 10 | 0 |
| qwen3:8b | 1 | **FAILED** | 600.02 | — | — | — |
| qwen3:8b | 2 | **FAILED** | 600.02 | — | — | — |
| qwen3:8b | 3 | **FAILED** | 600.02 | — | — | — |
| qwen3:8b | 4 | **FAILED** | 600.02 | — | — | — |
| qwen3:14b | 0 | OK | 241.00 | 5 (fluency, vocabulary, grammar, coherence, relevance — all distinct) | 5 | 0 |
| qwen3:14b | 1 | OK | 253.27 | 5 (all distinct) | 5 | 0 |
| qwen3:14b | 2 | OK | 222.10 | 5 (all distinct) | 5 | 0 |
| qwen3:14b | 3 | OK | 237.86 | 5 (all distinct) | 5 | 0 |
| qwen3:14b | 4 | OK | 312.56 | 5 (all distinct) | 5 | 0 |

All four `qwen3:8b` failures raised `TimeoutError: timed out` at the
`OllamaClient`'s own 600s HTTP timeout — a real production failure mode, not a
harness artifact. The model was evicted and reloaded (`ollama stop qwen3:8b`)
before trial 4 to rule out server-side context buildup from the earlier
timed-out requests; the next call still timed out at 600s, so the slowdown is
not explained by leftover state from the aborted prior calls.

Trial 0 (the only `qwen3:8b` success) is also not a valid five-dimension
response by content, even though it satisfies the JSON schema's `minItems`/
`maxItems=5` array-length check: its `dimensions` array contains `"grammar"`
twice and never contains `"relevance"` at all. `RATING_SCHEMA` does not
constrain the `dimension` enum values to be distinct, so a model can pad the
array with a repeated dimension and pass validation while silently skipping
one of the five real dimensions. Counting only genuinely valid five-distinct-
dimension responses, `qwen3:8b` is **0 for 5**, not 1 for 5.

`qwen3:14b` produced five distinct, correctly-dimensioned responses in five
attempts, with 5/5 evidence items surviving `parse_rating`'s verbatim-quote
filter in every trial — zero discarded across all 25 evidence items offered.

## One full Korean rating from each model (trial 0, verbatim)

### qwen3:8b, trial 0

```json
{
  "dimensions": [
    {
      "dimension": "fluency",
      "level": "AL",
      "comment_ko": "구체적인 경험을 자연스럽게 전달하고 있으나, 문맥상 약간의 혼동이 보인다.",
      "evidence": [
        {
          "quote": "I think the most memorable trip was when I visited Jeju-do, Jeju-do is a island in South Korea",
          "issue_ko": "Jeju-do를 두 번 언급하며 반복이 발생했다.",
          "correction_en": "Jeju-do를 한 번만 언급하고, 설명을 이어가도록 하자."
        },
        {
          "quote": "we to the the hotel",
          "issue_ko": "to the the hotel",
          "correction_en": "to the hotel"
        }
      ]
    },
    {
      "dimension": "grammar",
      "level": "AL",
      "comment_ko": "문법적으로는 대부분 정확하지만, 일부 표현이 자연스럽지 않다.",
      "evidence": [
        {
          "quote": "Jeju is like Hawaii but in Korea something like that",
          "issue_ko": "something like that",
          "correction_en": "something like that"
        },
        {
          "quote": "we just sit in there I see the sunset",
          "issue_ko": "we just sit in there I see the sunset",
          "correction_en": "we just sat there and I saw the sunset"
        }
      ]
    },
    {
      "dimension": "vocabulary",
      "level": "AL",
      "comment_ko": "일상적인 표현을 사용하며, 어휘 다양성이 부족하다.",
      "evidence": [
        {
          "quote": "I think the most part was just stay there",
          "issue_ko": "the most part was just stay there",
          "correction_en": "the most part was just staying there"
        },
        {
          "quote": "we take a bath there and just relaxing",
          "issue_ko": "take a bath there and just relaxing",
          "correction_en": "took a bath there and just relaxed"
        }
      ]
    },
    {
      "dimension": "coherence",
      "level": "AL",
      "comment_ko": "전체적인 이야기 흐름은 좋지만, 세부적인 설명이 부족하다.",
      "evidence": [
        {
          "quote": "I think the most memorable trip was when I visited Jeju-do",
          "issue_ko": "I think the most memorable trip was when I visited Jeju-do",
          "correction_en": "I think the most memorable trip was when I visited Jeju-do"
        },
        {
          "quote": "everything was new for me so was amazing",
          "issue_ko": "everything was new for me so was amazing",
          "correction_en": "everything was new for me, so it was amazing"
        }
      ]
    },
    {
      "dimension": "grammar",
      "level": "AL",
      "comment_ko": "문법적으로는 대부분 정확하지만, 일부 표현이 자연스럽지 않다.",
      "evidence": [
        {
          "quote": "Jeju is like Hawaii but in Korea something like that",
          "issue_ko": "something like that",
          "correction_en": "something like that"
        },
        {
          "quote": "we just sit in there I see the sunset",
          "issue_ko": "we just sit in there I see the sunset",
          "correction_en": "we just sat there and I saw the sunset"
        }
      ]
    }
  ]
}
```

Note the duplicated `"grammar"` entry (items 2 and 5, identical content) and
the absent `"relevance"` dimension.

### qwen3:14b, trial 0

```json
{
  "dimensions": [
    {
      "dimension": "fluency",
      "level": "IH",
      "comment_ko": "발음과 어휘 사용이 일반적인 수준이지만, 'I think the most memorable trip was when I visited Jeju-do'와 같은 문장에서 연결 어미가 부족해 자연스러운 흐름이 약간 끊기는 경우가 있다.",
      "evidence": [
        {
          "quote": "I think the most memorable trip was when I visited Jeju-do",
          "issue_ko": "문장 구조가 간결하지 않아 자연스러운 말하기가 어렵다.",
          "correction_en": "The most memorable trip I took was when I visited Jeju-do."
        }
      ]
    },
    {
      "dimension": "vocabulary",
      "level": "IH",
      "comment_ko": "기본적인 어휘를 잘 사용했지만, 'at the moment was honestly an amazing experience'와 같은 표현에서 어휘 선택이 부자연스러운 경우가 있다.",
      "evidence": [
        {
          "quote": "at the moment was honestly an amazing experience",
          "issue_ko": "문법 구조가 혼란스럽고, 'at the moment'의 사용이 부적절하다.",
          "correction_en": "It was honestly an amazing experience."
        }
      ]
    },
    {
      "dimension": "grammar",
      "level": "IH",
      "comment_ko": "기본 문법 구조는 이해 가능하지만, 'we to the the hotel'과 같은 문법 오류가 자주 발생한다.",
      "evidence": [
        {
          "quote": "we to the the hotel",
          "issue_ko": "동사 'go'가 누락되었고, 'the the'는 중복된 어휘 사용이다.",
          "correction_en": "we went to the hotel"
        }
      ]
    },
    {
      "dimension": "coherence",
      "level": "IH",
      "comment_ko": "전체적으로 이야기의 흐름은 있지만, 'we have a jacuzzi so we take a bath there and just relaxing'과 같은 문장에서 논리적 연결이 약하다.",
      "evidence": [
        {
          "quote": "we have a jacuzzi so we take a bath there and just relaxing",
          "issue_ko": "문장의 연결이 부자연스럽고, 'relaxing'은 동사형으로 사용되어야 한다.",
          "correction_en": "we had a jacuzzi, so we took a bath there and just relaxed."
        }
      ]
    },
    {
      "dimension": "relevance",
      "level": "IH",
      "comment_ko": "질문에 대한 답변은 대부분 관련성이 있지만, 'Jeju is like Hawaii but in Korea something like that'과 같은 표현에서 주제가 약간 흐려지는 경우가 있다.",
      "evidence": [
        {
          "quote": "Jeju is like Hawaii but in Korea something like that",
          "issue_ko": "비유 표현이 부자연스럽고, 주제를 명확히 전달하지 못한다.",
          "correction_en": "Jeju is like Hawaii, but it's in Korea."
        }
      ]
    }
  ]
}
```

**On the Korean itself (criterion 3): left to the reader.** No automated check
can judge whether `comment_ko`/`issue_ko` read as natural, technically
accurate Korean. Both full outputs are quoted above verbatim so the comparison
can be made without re-running anything. This note does not attempt that
judgement — the pin below is decided on criteria 1 and 2 alone.

## Decision

Pinned `OLLAMA_MODEL = "qwen3:14b"`. `qwen3:8b` failed criterion 1 outright:
four of five attempts raised a timeout at the client's own 600s limit, and its
one completed attempt did not actually cover all five dimensions (duplicated
`grammar`, missing `relevance`). `qwen3:14b` met criterion 1 (5/5 valid,
five distinct dimensions every time) and criterion 2 (25/25 evidence items
survived the quote filter, 0 discarded).

Estimated evaluation time for a full fifteen-question exam: the five
`qwen3:14b` rating trials averaged 253s (≈4.2 minutes) per call, so fifteen
questions is about **63 minutes** of rating, plus about twelve minutes of
transcription.
