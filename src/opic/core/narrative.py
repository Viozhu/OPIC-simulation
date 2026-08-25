"""The read of an exam that a template cannot produce.

`report.py` derives everything a second reading of `result.json` can reach.
What is left over is judgement: which named patterns the corrections fall
into, what a number means, and how an answer would sound one band higher.
This module is the shape of that judgement and nothing else — no prompt, no
transport, no model. A `Narrative` arrives from a `NarrativeWriter` port, and
`page.py` renders it beside the derived sections or renders those alone.

Every field is optional to the page. An exam graded with `OPIC_LLM=ollama`, or
with no credentials, or against a model that returned something the schema
rejected, still gets its report — with these sections absent rather than
filled with sentences that are true of every exam.
"""

from __future__ import annotations

from dataclasses import dataclass

from opic.core.report import Report


@dataclass(frozen=True, slots=True)
class PatternItem:
    """One correction, placed under the pattern it belongs to.

    Carries no text of its own: `quote`, `correction_en` and `issue_ko` are
    copied from an evidence item the rater already produced. The adapter checks
    that they were, which is what stops a narrative from quoting a sentence the
    candidate never said.
    """

    answer_index: int
    quote: str
    correction_en: str
    issue_ko: str


@dataclass(frozen=True, slots=True)
class ErrorPattern:
    title_ko: str
    blurb_ko: str
    items: tuple[PatternItem, ...]


@dataclass(frozen=True, slots=True)
class GapSection:
    """The single weakest thing in the exam, named and shown.

    `answer_indexes` points at the answers that made the case, so the page can
    print them in full underneath rather than asking the reader to go and find
    them.
    """

    title_ko: str
    blurb_ko: str
    answer_indexes: tuple[int, ...]
    close_ko: str


@dataclass(frozen=True, slots=True)
class Caveat:
    title_ko: str
    body_ko: str


@dataclass(frozen=True, slots=True)
class Analysis:
    verdict_ko: str
    dimensions_lede_ko: str
    dimensions_close_ko: str
    distribution_ko: str
    patterns: tuple[ErrorPattern, ...]
    patterns_close_ko: str
    gap: GapSection | None
    splits_close_ko: str
    sound_ko: str
    caveats: tuple[Caveat, ...]


@dataclass(frozen=True, slots=True)
class AnswerRewrite:
    """One answer as it would sound at the top of the scale.

    `invented` is the honest flag. Two of the fifteen questions on a real exam
    asked for a specific past experience and got a routine, so there was no
    episode in the transcript to rewrite and writing one meant making it up.
    An invented episode is legitimate as a worked example and is not the
    candidate's memory, so the page has to say which it is — a study document
    that hands someone a fabricated story about themselves, unlabelled, is
    worse than one that hands them a blank to fill.
    """

    answer_index: int
    text_en: str
    why_ko: str
    invented: bool


@dataclass(frozen=True, slots=True)
class Narrative:
    analysis: Analysis | None
    rewrites: tuple[AnswerRewrite, ...]

    def rewrite_for(self, answer_index: int) -> AnswerRewrite | None:
        for rewrite in self.rewrites:
            if rewrite.answer_index == answer_index:
                return rewrite
        return None


def quotes_in_report(report: Report) -> frozenset[tuple[str, str]]:
    """Every (quote, correction) pair the rater actually produced.

    Taken from the per-answer detail, which keeps every evidence item, rather
    than from the exam-level summary, which is capped at three per dimension.
    A narrative whose pattern items are not all in here is rejected: the model
    is grouping the rater's findings, not adding to them.
    """
    return frozenset(
        (item.quote, item.correction_en)
        for answer in report.answers
        for score in answer.scores
        for item in score.evidence
    )
