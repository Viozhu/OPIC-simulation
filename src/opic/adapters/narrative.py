"""Prompts, schemas and guards for the part of the report a model writes.

Shared the way `llm.py` is shared: the prompts and the parsing live here, and
an adapter adds only transport. Two calls, not one — the analysis and the
fifteen rewrites are independent, and a single response carrying both is a
single point of truncation.

Everything a model returns passes through `parse_analysis` or `parse_rewrites`
before it reaches `core/narrative.py`, and those two functions are where the
promises the page relies on are actually kept:

  * a pattern may only quote an evidence item the rater already produced,
  * prose may only carry <b>, <i> and <code>, because `page.py` inserts it
    without escaping,
  * `invented` defaults to true, never to false.
"""

from __future__ import annotations

import html
from typing import Any

from opic.adapters.fencing import FENCE_RULE, fenced, mint
from opic.core.narrative import (
    Analysis,
    AnswerRewrite,
    Caveat,
    ErrorPattern,
    GapSection,
    PatternItem,
    quotes_in_report,
)
from opic.core.report import Report, format_metrics

MIN_REWRITE_WORDS = 90
MAX_REWRITE_WORDS = 200

# The page inserts narrative prose into HTML without escaping it, so this is
# the whole list of markup a model is allowed to reach the page with. Anything
# else it writes arrives as text.
ALLOWED_TAGS = ("b", "i", "code")

# A question asking for one past episode, in the wordings the question writer
# actually produces. Answering one of these with a routine is the most
# expensive mistake available on this exam — it cost two answers their
# relevance band on a real run — and a rewrite that keeps the routine framing
# teaches nothing. General instruction was not enough to stop that: across
# runs the model would narrate an episode for one such answer and describe a
# routine for another in the same batch. So the demand is marked on the answer
# itself, where it cannot be skimmed past.
EPISODE_MARKERS = (
    "a particular time",
    "a specific time",
    "a specific vacation",
    "a time when",
    "that stands out",
    "what happened",
)


def asks_for_an_episode(question_en: str) -> bool:
    lowered = question_en.lower()
    return any(marker in lowered for marker in EPISODE_MARKERS)


class NarrativeError(ValueError):
    """The model returned something the page must not be asked to render."""


def clean_markup(text: str) -> str:
    """Escape everything, then let the three allowed tags back through.

    Deny by default. A model that decides to emit a `<script>` or an `onclick`
    gets it rendered as visible text, which is exactly what should happen to
    it: the page is a file the candidate opens in a browser, and nothing a
    grading model writes has any business executing there.
    """
    out = html.escape(text.strip(), quote=False)
    for tag in ALLOWED_TAGS:
        out = out.replace(f"&lt;{tag}&gt;", f"<{tag}>")
        out = out.replace(f"&lt;/{tag}&gt;", f"</{tag}>")
    return out


def _prose(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise NarrativeError(f"{key} is missing or empty")
    return clean_markup(value)


# ------------------------------------------------------------------- schemas

_PROSE = {"type": "string", "minLength": 1, "maxLength": 700}
_SHORT = {"type": "string", "minLength": 1, "maxLength": 120}

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "verdict_ko",
        "dimensions_lede_ko",
        "dimensions_close_ko",
        "distribution_ko",
        "patterns",
        "patterns_close_ko",
        "gap",
        "splits_close_ko",
        "sound_ko",
        "caveats",
        "closing_recap_ko",
        "closing_why_ko",
    ],
    "properties": {
        "verdict_ko": _PROSE,
        "dimensions_lede_ko": _PROSE,
        "dimensions_close_ko": _PROSE,
        "distribution_ko": _PROSE,
        "patterns": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {
                "type": "object",
                "required": ["title_ko", "blurb_ko", "items"],
                "properties": {
                    "title_ko": _SHORT,
                    "blurb_ko": _PROSE,
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": [
                                "answer_index",
                                "quote",
                                "correction_en",
                                "issue_ko",
                            ],
                            "properties": {
                                "answer_index": {"type": "integer", "minimum": 0},
                                "quote": {"type": "string", "minLength": 1},
                                "correction_en": {"type": "string", "minLength": 1},
                                "issue_ko": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                },
            },
        },
        "patterns_close_ko": _PROSE,
        "gap": {
            "type": "object",
            "required": ["title_ko", "blurb_ko", "answer_indexes", "close_ko"],
            "properties": {
                "title_ko": _SHORT,
                "blurb_ko": _PROSE,
                "answer_indexes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {"type": "integer", "minimum": 0},
                },
                "close_ko": _PROSE,
            },
        },
        "splits_close_ko": _PROSE,
        "sound_ko": _PROSE,
        "caveats": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["title_ko", "body_ko"],
                "properties": {"title_ko": _SHORT, "body_ko": _PROSE},
            },
        },
        "closing_recap_ko": _PROSE,
        "closing_why_ko": _PROSE,
    },
}

REWRITES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["rewrites"],
    "properties": {
        "rewrites": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["answer_index", "text_en", "why_ko", "invented"],
                "properties": {
                    "answer_index": {"type": "integer", "minimum": 0},
                    "text_en": {"type": "string", "minLength": 200},
                    "why_ko": _PROSE,
                    "invented": {"type": "boolean"},
                },
            },
        }
    },
}


# --------------------------------------------------------------------- parsing


def parse_analysis(payload: dict, report: Report) -> Analysis:
    """The analysis, with every quote checked against what the rater produced.

    The model's job in the pattern sections is to name and group the rater's
    findings. A quote it did not get from the report is either a sentence the
    candidate never said or a correction nobody proposed, and either one makes
    the page a liar, so the whole analysis is rejected rather than shown with
    one bad card in it.
    """
    allowed = quotes_in_report(report)
    known = {answer.index for answer in report.answers}

    patterns = []
    for raw in payload.get("patterns") or []:
        items = []
        for item in raw.get("items") or []:
            quote = str(item.get("quote", "")).strip()
            correction = str(item.get("correction_en", "")).strip()
            index = item.get("answer_index")
            if (quote, correction) not in allowed:
                raise NarrativeError(
                    f"pattern quotes {quote!r} → {correction!r}, which is not an "
                    "evidence item in this exam"
                )
            if index not in known:
                raise NarrativeError(f"pattern points at answer {index}, which is absent")
            items.append(
                PatternItem(
                    answer_index=int(index),
                    quote=quote,
                    correction_en=correction,
                    issue_ko=clean_markup(str(item.get("issue_ko", ""))),
                )
            )
        if not items:
            raise NarrativeError("a pattern arrived with no items")
        patterns.append(
            ErrorPattern(
                title_ko=_prose(raw, "title_ko"),
                blurb_ko=_prose(raw, "blurb_ko"),
                items=tuple(items),
            )
        )
    if not patterns:
        raise NarrativeError("no error patterns")

    raw_gap = payload.get("gap") or {}
    indexes = tuple(
        int(i) for i in (raw_gap.get("answer_indexes") or []) if i in known
    )
    gap = (
        GapSection(
            title_ko=_prose(raw_gap, "title_ko"),
            blurb_ko=_prose(raw_gap, "blurb_ko"),
            answer_indexes=indexes,
            close_ko=_prose(raw_gap, "close_ko"),
        )
        if indexes
        else None
    )

    return Analysis(
        verdict_ko=_prose(payload, "verdict_ko"),
        dimensions_lede_ko=_prose(payload, "dimensions_lede_ko"),
        dimensions_close_ko=_prose(payload, "dimensions_close_ko"),
        distribution_ko=_prose(payload, "distribution_ko"),
        patterns=tuple(patterns),
        patterns_close_ko=_prose(payload, "patterns_close_ko"),
        gap=gap,
        splits_close_ko=_prose(payload, "splits_close_ko"),
        sound_ko=_prose(payload, "sound_ko"),
        caveats=tuple(
            Caveat(
                title_ko=_prose(raw, "title_ko"), body_ko=_prose(raw, "body_ko")
            )
            for raw in payload.get("caveats") or []
        ),
        closing_recap_ko=_prose(payload, "closing_recap_ko"),
        closing_why_ko=_prose(payload, "closing_why_ko"),
    )


def parse_rewrites(payload: dict, report: Report) -> tuple[AnswerRewrite, ...]:
    """The rewrites that name a real answer, at most one per answer.

    A short set is kept rather than rejected: the page renders a rewrite where
    it has one and the question and transcript alone where it does not, so
    thirteen good rewrites are worth thirteen good rewrites. An unknown index
    or a second rewrite for the same answer is dropped — both mean the model
    lost track of which answer it was on, and neither can be rendered.
    """
    scored = {
        answer.index for answer in report.answers if answer.state == "scored"
    }
    seen: set[int] = set()
    out: list[AnswerRewrite] = []
    for raw in payload.get("rewrites") or []:
        index = raw.get("answer_index")
        if index not in scored or index in seen:
            continue
        text = str(raw.get("text_en", "")).strip()
        if not text:
            continue
        seen.add(int(index))
        out.append(
            AnswerRewrite(
                answer_index=int(index),
                text_en=text,
                why_ko=clean_markup(str(raw.get("why_ko", ""))),
                # Absent means unknown, and unknown must read as invented: the
                # flag exists to stop an invented episode from being presented
                # as the candidate's own, so its default has to be the safe
                # direction rather than the flattering one.
                invented=bool(raw.get("invented", True)),
            )
        )
    if not out:
        raise NarrativeError("no usable rewrites")
    return tuple(out)


# --------------------------------------------------------------------- prompts


def _exam_sheet(report: Report, with_evidence: bool = True) -> str:
    """The whole exam as plain text, one block per answer.

    Both prompts get the same sheet. A model asked to find what repeats across
    fifteen answers cannot do it from one answer at a time, and a model asked
    to rewrite answer nine needs the other fourteen to know what the candidate
    has already told the examiner about herself.

    Which is also what makes this sheet worth fencing: fifteen transcripts
    reach one prompt here, so a single answer spoken as an instruction would be
    read while the model writes about all fifteen. Each transcript is fenced
    on its own rather than the sheet as a whole, because the sheet also carries
    lines that ARE instructions — the levels, the episode demand — and those
    belong outside. One token for the whole sheet, minted against every
    transcript in it.

    The evidence lines are the one place candidate words still travel unfenced.
    They are left that way on purpose: the analysis prompt requires the model
    to copy `quote` and `correction_en` character for character, and markers
    around them would put two more strings in reach of that copy. They are also
    the rater's short excerpts rather than the whole answer, and they only exist
    because `parse_rating` found them verbatim in a transcript that was fenced
    when it was rated.
    """
    nonce = mint(*(answer.transcript_text for answer in report.answers))
    lines: list[str] = []
    for answer in report.answers:
        if answer.state != "scored":
            lines.append(f"[{answer.index:02d}] NOT SCORED ({answer.state})")
            continue
        levels = " ".join(
            f"{score.dimension.value}={score.level.name}" for score in answer.scores
        )
        head = f"[{answer.index:02d}] {answer.qtype_label_ko}"
        if answer.topic_label_ko:
            head += f" · {answer.topic_label_ko}"
        lines.append(f"{head} | {levels}")
        if answer.metrics is not None:
            lines.append(
                f"  numbers: {answer.metrics.words_per_minute:.0f} wpm, "
                f"{answer.metrics.duration_s:.0f}s, "
                f"{answer.metrics.word_count:.0f} words"
            )
        lines.append(f"  question: {answer.question_en}")
        if not with_evidence and asks_for_an_episode(answer.question_en):
            lines.append(
                "  >>> THIS QUESTION ASKS FOR ONE PAST EPISODE. The rewrite must "
                "narrate a single event — one day, one sequence, one past tense "
                "held throughout, an outcome. If the transcript has no episode, "
                "invent a small plausible one out of what she does mention and "
                "set invented=true. A rewrite that describes a routine here is "
                "wrong even if every word of it is true."
            )
        lines.append("  transcript:")
        lines.append(fenced(answer.transcript_text, nonce))
        if with_evidence:
            for score in answer.scores:
                for item in score.evidence:
                    lines.append(
                        f"  evidence[{score.dimension.value}]: "
                        f'"{item.quote}" -> "{item.correction_en}" '
                        f"({item.issue_ko})"
                    )
        lines.append("")
    return "\n".join(lines)


def _overview(report: Report) -> str:
    dimensions = "\n".join(
        f"  {d.label_ko} ({d.dimension.value}, weight {d.weight:.0%}): {d.level.name}"
        for d in report.dimensions
    )
    by_type = "\n".join(f"  {label}: {level.name}" for _, label, level in report.by_type)
    by_topic = "\n".join(
        f"  {label}: {level.name}" for _, label, level in report.by_topic
    )
    averages = ""
    if report.averages is not None:
        averages = ", ".join(
            f"{key} {value}" for key, value in format_metrics(report.averages).items()
        )
    limiting = ""
    if report.limiting is not None:
        limiting = (
            f"\nThe final level was capped one band by {report.limiting.label_ko}; "
            f"without that cap it would be {report.limiting.without_cap.name}."
        )
    return f"""Final level: {report.final_level.name}
Answers scored: {report.scored_answers} of {report.expected_answers}
Dimensions:
{dimensions}
By question type:
{by_type}
By topic:
{by_topic}
Exam averages: {averages}{limiting}"""


def analysis_prompt(report: Report) -> str:
    return f"""You are writing the analysis sections of a Korean-language report
on one OPIc mock exam. The candidate is Korean and reads Korean; the exam was
spoken in English. Everything you write goes to a `_ko` field and must be in
Korean, except the English quotes, which are already fixed.

{_overview(report)}

The exam, answer by answer, with the grader's evidence. {FENCE_RULE}

{_exam_sheet(report)}

Write:

- verdict_ko: two or three sentences on what {report.final_level.name} means in
  plain terms. Say where it sits on the nine-band scale and what the candidate
  can and cannot yet do. No encouragement, no scolding.
- dimensions_lede_ko: what the spread between the five dimensions says. Name
  the highest and the lowest and what their gap means.
- dimensions_close_ko: the one thing that follows from that spread.
- distribution_ko: what the shape of the level counts says. Which dimension is
  holding the final level down, and how you can tell.
- patterns: group the grammar and vocabulary evidence above into named
  patterns — between two and five of them. Each pattern gets a Korean title
  that names the mistake ("관사의 과잉 사용"), a blurb explaining why it
  happens for a Korean speaker, and its items. YOU MAY ONLY USE `quote` and
  `correction_en` STRINGS THAT APPEAR VERBATIM IN THE EVIDENCE LINES ABOVE.
  Copy them character for character. Do not write a quote of your own, do not
  fix a typo in one, do not merge two. `issue_ko` may be your own words.
  Leave an evidence item out if it fits no pattern.
- patterns_close_ko: what is left over, or what to practise first.
- gap: the single weakest thing in this exam. `answer_indexes` are the one to
  three answers that make the case, `title_ko` names it as a finding, and
  `close_ko` says what to do about it. Prefer a gap that is cheap to fix.
- splits_close_ko: what the by-type and by-topic tables show.
- sound_ko: what the measured numbers say about how the candidate sounds, and
  what they do not say. The confidence figures are the recogniser's, not a
  pronunciation grade.
- caveats: at most two limits of this measurement that a reader should know —
  properties of the tool, not advice for the candidate. Skip any you cannot
  support from the data above.
- closing_recap_ko: the last thing the candidate reads. Three or four sentences
  reading the whole report back: what this exam showed she can already do, what
  it showed she cannot yet, and the one thing to work on first. Name answer
  numbers. Do not introduce a finding that is not already above.
- closing_why_ko: why the final level is {report.final_level.name} and not the
  band above or the band below it. The page prints the arithmetic next to this
  — the per-dimension medians, the weighted mean, the advanced-set raise and
  the weak-dimension cap — so do not restate the numbers. Say which of those
  steps actually decided it, and what would have had to be different in the
  answers for the next band up.

Write like a teacher who has read the whole exam once and is telling the
candidate what they actually heard. Specific over general: name the answer
number. No lists of adjectives. Plain markup only: <b>, <i>, <code>."""


def rewrites_prompt(report: Report) -> str:
    scored = [a.index for a in report.answers if a.state == "scored"]
    indexes = ", ".join(f"{i:02d}" for i in scored)
    return f"""You are rewriting each answer of a Korean candidate's OPIc mock
exam as it would sound at AL — Advanced Low, the top of the nine-band scale —
so that she can see the distance and read the target aloud.

The exam, answer by answer. {FENCE_RULE}

{_exam_sheet(report, with_evidence=False)}

Write one rewrite for every one of these answers: {indexes}.

What AL sounds like, and what you are aiming at:
- Paragraph-length connected speech, {MIN_REWRITE_WORDS}–{MAX_REWRITE_WORDS}
  words, with an opening and a close rather than a list of sentences.
- Narration held in one tense from start to finish when the question asks for a
  past episode. Present for habits. Conditionals handled without collapsing.
- Subordination and relative clauses; contrast made explicit ("I do X, but what
  I really…"); a reason behind each claim.
- Spoken register. This is something she will say out loud, not an essay. A
  question back to the examiner at the end is natural where the original had
  one.

The hard rule about content: BUILD EACH REWRITE OUT OF WHAT SHE ACTUALLY SAID.
You may use any fact from any of her answers, not just the one you are
rewriting — the same city, the same dog, the same husband, the same gym
machine. The point is a version of her own answer she could have given, not a
better candidate's answer.

Do not add a fact about her life that is not somewhere in the transcripts. Not
a job, not a family member, not a place she lives or works, not a hobby. If she
never said what she does for a living, the rewrite does not say either — talk
about what she did say instead. Length is not a reason to invent a biography;
detail about something she mentioned is always available.

One case overrides the rule above. Some questions ask for one specific past
experience — "a particular time", "a specific time", "tell me what happened" —
and got a description of a routine instead. Answering those with a routine is
the single most expensive mistake on this exam, so a rewrite that keeps the
routine framing teaches her nothing, however faithful it is. There you MUST
narrate one episode: a day, a sequence of events, one past tense held from
start to finish, an outcome. Invent the episode if the transcript has none —
build it out of things she does mention, keep it small and plausible, and set
`invented` to true. "There was no episode to work from" is not an acceptable
outcome; the whole point is to show her what the shape of that answer is.

`invented` is true whenever the rewrite contains anything she did not say —
an episode you had to make up, or any added fact about her life. It is false
only when every detail in it came from the transcripts. The page prints a
warning next to a rewrite marked true and tells her to swap in what really
happened, so a false flag on an invented detail is the one failure here that
actually costs her something. When in doubt, true.

`why_ko`: one Korean sentence naming what changed — the structural move, not
praise. If you changed what the answer is about because the original answered a
different question, say that first, in <b>bold</b>."""
