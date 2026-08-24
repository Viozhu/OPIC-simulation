# The exam in a browser — design

The simulator's web front end has been correct for three phases and plain for
all three. Every screen works; none of them tells the candidate what is
happening while it works. This design closes four gaps, in the order they hurt:
the candidate cannot see that the microphone is hearing them, the finished
report is drawn twice and the browser gets the poorer drawing, the page has one
theme and glued-together buttons, and a screen reader is told nothing when the
step changes.

Nothing in `core/` changes except that `core/page.py` gains a second reader.
The exam's state machine, its API, and its grading path are untouched.

## Who this is for

One candidate on a desktop browser, and one remote family member reaching the
same laptop through the `share-test` tunnel — Chrome and Safari, on a machine
whose microphone nobody has tested. Phone layouts are out of scope. So is
translating anything: the UI speaks Korean, as it does today.

## §1 The report: one renderer, not three

`core/page.py` renders the whole report — the nine-band ladder, the level
distribution, the words-per-minute chart, the type and topic splits, the
answer table, a block per answer, both themes — and `session/pages.py` writes
it to `report-ko.html` when the worker finishes grading. `done.js` renders the
same `Report` in the browser, worse: a heading, four flat lists, and a `<pre>`
of the raw JSON.

The browser will show the rendered page instead.

```
GET /api/sessions/{session_id}/page  ->  text/html
```

`session/pages.py` grows one function:

```python
def html_for(root: Path, session_id: str) -> str | None:
    """The report page for a session, from disk if it is there.

    The written file is the better answer whenever it exists: it is the one
    the worker rendered with a narrative. Rendering on demand is the fallback
    for a session graded before this existed, or one whose narrative call
    failed — same page, minus the judged sections.
    """
```

It reads `store.page_path(root, session_id)` when that file exists, and
otherwise calls the `build()` that is already there and `render_html(report,
meta, None)`. A GET never writes to disk: a read request that leaves a file
behind is a read request that can fail in a new way.

The endpoint 404s when `html_for` returns `None`, which is exactly when
`result.json` is absent or every answer file is unreadable — the same
condition `/report` already 404s on.

`done.js` becomes a shell:

- an `<iframe>` filling the width, `src` pointing at the endpoint
- a link that opens the same URL in a new tab, for printing or saving
- the "새 시험 시작" button that is there today, which still clears
  `localStorage` and reloads

`renderMinimal` and `renderRetry` stay exactly as they are. They are the
fallback when the iframe's fetch fails: `done.js` probes the endpoint with a
`HEAD` before mounting the iframe, so a 404 lands on `renderMinimal` (level and
dimensions from `/result`) and a total failure lands on `renderRetry`. The
degradation ladder the phase-4 work built is preserved rung for rung; only the
top rung gets better.

The share gate needs no change. Its cookie is `samesite=lax` on the same
origin, so a same-origin iframe carries it.

## §2 Feedback while recording

Today a candidate who has allowed the microphone sees the word "녹음 중…" and
nothing else. If the wrong input device is selected, or the gain is at zero,
they find out when the report says the transcript was empty.

**`static/meter.js`** — new module, one export:

```js
export function levelMeter(stream)  // -> {element, peak, stop}
```

An `AudioContext` and an `AnalyserNode` on the stream `recorder.js` already
holds, sampled per animation frame, RMS mapped to the width of a bar.
`peak()` returns the loudest RMS seen since the meter started. `stop()`
releases the context.

Everything in it is wrapped: if `AudioContext` is missing, blocked, or throws,
`levelMeter` returns `{element: null, peak: () => null, stop: () => {}}` and
the caller renders nothing extra. The meter is decoration on a critical path
and must never be able to take the path down. A `peak()` of `null` means "not
measured" and is never treated as "silent".

`recorder.js` exposes the `stream` on its session object so the meter can
attach without a second `getUserMedia` call — a second call would prompt again
on some browsers and is a second thing that can fail.

`question.js` passes the stream out through the state callback:
`onState("recording", {stream})`. The sample step and the test step both
receive it, so the rehearsal rehearses the real screen.

**Setup (3단계)** mounts the meter next to the record button and keeps the
peak. When recording stops:

- peak above the threshold → "목소리가 잘 들립니다" and the existing playback
- peak below it → a `.issues` line saying no voice was detected and suggesting
  the input device, **and 다음 stays enabled**

Blocking here was considered and rejected: a meter bug or an unusual device
would strand a remote candidate before the exam starts, which is worse than an
exam recorded quietly. The warning is the whole intervention.

Threshold: RMS peak `0.02`, chosen as a floor well under speech and well over
line noise. It lives as a named constant in `meter.js` with that reasoning in a
comment, because it is the kind of number a future reader will otherwise
assume was measured.

**Test (5단계)** mounts the same meter plus an `mm:ss` elapsed counter that
starts when the phase becomes `recording` and stops on 다음. Neither judges
anything — no warning, no block. A candidate mid-exam can act on a level bar;
they cannot act on being told their answer was too quiet after it is gone.

**Progress.** `index.html` gains a `<progress>` in the header. `app.js` fills
it on every `show()`: during `test`, answered out of total; during `grading`,
settled out of expected; hidden on every other step. The existing "질문 3 / 15"
heading stays — the bar is the glance, the heading is the fact.

`grading.js` gets the same `<progress>` inline, alongside the counter it prints
today, and keeps its text ETA.

## §3 One visual family

`style.css` is rewritten around the token set `PAGE_CSS` already defines:
`--ground --surface --sunk --ink --ink-2 --ink-3 --rule --rule-2 --accent
--accent-soft --accent-ink --crit --warn --good --shadow`, with the same
values, plus the three `@media (prefers-color-scheme: dark)` and
`[data-theme]` blocks in the same shape. The exam and the report then read as
one product rather than two.

The tokens are copied, not extracted into a shared file. `core/page.py` must
stay self-contained: a report opened in six months with no server running
cannot depend on a stylesheet served by that server. The duplication is
deliberate and carries a comment saying so on both sides, naming the other.

The SPA does **not** link Google Fonts, though `page.py` does. It uses the same
font stacks with the webfont name dropped, so it inherits the system Korean
face. The exam has to start on a laptop with no network beyond the tunnel, and
a blocking font fetch is a way for the first screen to be slow for no reason.
The report page is a document that can wait a beat for its typeface; the exam
is not.

Beyond tokens: `gap` on the button rows that are flush against each other
today, a `max-width` and padding that survive a narrow window, focus rings that
are visible rather than the browser default on a coloured button, and
`:disabled` styling that reads as disabled without relying on opacity alone.

## §4 What a screen reader gets

- `#step-label` becomes `aria-live="polite"`, so the step announces itself.
- Each step's status paragraph — the one that cycles 질문 재생 중 / 녹음 중 /
  전송 중 — becomes an `aria-live="polite"` region created once per step
  rather than a paragraph whose `textContent` is replaced silently.
- `app.js` moves focus to the step's first heading after `show()` renders, so
  a keyboard user is not returned to the top of the document each time.
- The waiting screens (`문제를 준비하고 있습니다`, 채점 중) set `aria-busy`.
- The `<progress>` elements carry their own labels.
- Error text in `.issues` gets `role="status"`, not `alert`: none of it is an
  interruption worth stealing focus for.

## Error handling, whole-design

| Failure | Behaviour |
|---|---|
| `AudioContext` unavailable or throws | no meter, recording unchanged |
| meter reports a low peak in setup | red warning, 다음 stays enabled |
| `/page` 404s or the HEAD probe fails | `renderMinimal` from `/result` |
| `/page` and `/result` both fail | `renderRetry`, as today |
| iframe loads but the page is empty | the new-tab link is still there |
| no `AnalyserNode` mid-exam | bar absent, timer still runs |

## Testing

The front end has no test runner and no build step — ES modules served raw —
and this design does not add one. That is a real constraint on the shape of the
work: the JS changes stay small, defensive, and independently observable, and
the Python changes carry the tests.

**pytest**

- `tests/web/test_report_page_route.py`: serves the written `report-ko.html`
  byte for byte when it exists; renders on demand when it does not; 404 without
  `result.json`; 404 when every answer file is unreadable; the share gate
  covers it like every other route.
- `tests/session/test_pages.py` gains `html_for`: file present → file content;
  file absent but session graded → rendered HTML containing the level; nothing
  graded → `None`; a `.tmp` left behind by an interrupted write is not served.

**By hand, in Chrome and in Safari**

Setup with the microphone muted, setup with it working, one full sample
question, one real question including 재생, the grading screen, and the report
in both themes. Safari matters because it is what the remote family member is
likely to have.

## Out of scope

Phone layouts. Internationalisation. Any change to `core/` beyond a second
caller for `page.py`. The uncommitted phase-5 work is a dependency of §1, not
part of this: §1 assumes `core/page.py`, `session/pages.py` and
`store.page_path` exist as they do in the working tree.
