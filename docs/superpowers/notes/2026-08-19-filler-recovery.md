# Filler recovery experiment (2026-08-19)

**Verdict: the experiment failed.** None of the three `initial_prompt` values
recovered any hesitation markers — every run counted 0 fillers against `evidence/sample-answer.wav`, far short of the pre-registered threshold of 3.

## Method

`evidence/sample-answer.wav` (90s, unscripted non-native English) was transcribed
three times with `WhisperModel("medium", device="cpu", compute_type="int8")`,
using `language="en"`, `word_timestamps=True`, `condition_on_previous_text=False`,
`temperature=0.0`, varying only `initial_prompt`. Filler counts were computed by
normalising each word with `opic.core.metrics._normalise` and checking
membership in `opic.core.metrics.FILLERS`.

## Results

### Run 1: `initial_prompt=None`

- Filler count: **0**
- First 200 characters: `"Hello, I will tell you about my memory trip I took, I think the most memorable trip was when I visited Jeju-do, Jeju-do is a island in South Korea and I visited there with my girlfriend at the moment "`

### Run 2: `initial_prompt="Um, uh, so, like, you know, I mean..."`

- Filler count: **0**
- First 200 characters: `"Hello, I will tell you about my memory trip I took. I think the most memorable trip was when I visited Jeju-do. Jeju-do is a island in South Korea and I visited there with my girlfriend at the moment."`

### Run 3: `initial_prompt="Uh... um... er... so uh... I mean, uh..."`

- Filler count: **0**
- First 200 characters: `"Hello, I will tell you about my memory trip I took. I think the most memorable trip was when I visited Jeju-do. Jeju-do is a island in South Korea and I visited there with my girlfriend at the moment."`

## Analysis

Neither prompt biased the decoder toward emitting hesitation markers on this
recording. The prompted runs (2 and 3) changed the transcript only in
punctuation (added periods/commas) and picked up 5 extra non-filler words
relative to run 1 (155 vs. 150 words) — no filler tokens of any kind appeared
in any run. The result is not marginal: it is a clean zero across all three
conditions, well below the pre-registered threshold of 3. The failure branch
is taken.

## Consequence

`filler_count` and `filler_rate` were removed from `AnswerMetrics`. A field that
always reads zero misrepresents what the system measures. If a future
speech-to-text engine preserves disfluencies, they come back with it.
