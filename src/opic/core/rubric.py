from __future__ import annotations

from enum import Enum


class ActflLevel(Enum):
    """The OPIc proficiency scale, ordered from lowest to highest."""

    NL = 0
    NM = 1
    NH = 2
    IL = 3
    IM1 = 4
    IM2 = 5
    IM3 = 6
    IH = 7
    AL = 8

    @property
    def rank(self) -> int:
        return self.value

    @classmethod
    def from_rank(cls, rank: int) -> ActflLevel:
        lowest = min(level.value for level in cls)
        highest = max(level.value for level in cls)
        return cls(max(lowest, min(highest, rank)))


class Dimension(Enum):
    """What the evaluator judges, one axis at a time."""

    FLUENCY = "fluency"
    GRAMMAR = "grammar"
    VOCABULARY = "vocabulary"
    COHERENCE = "coherence"
    RELEVANCE = "relevance"


DIMENSION_WEIGHTS: dict[Dimension, float] = {
    Dimension.FLUENCY: 0.25,
    Dimension.GRAMMAR: 0.20,
    Dimension.VOCABULARY: 0.20,
    Dimension.COHERENCE: 0.20,
    Dimension.RELEVANCE: 0.15,
}

DIMENSION_LABELS_KO: dict[Dimension, str] = {
    Dimension.FLUENCY: "유창성",
    Dimension.GRAMMAR: "문법",
    Dimension.VOCABULARY: "어휘",
    Dimension.COHERENCE: "구성력",
    Dimension.RELEVANCE: "질문 적합성",
}


# Condensed from the ACTFL Proficiency Guidelines 2024 — Speaking, plus the
# Korean subdivision of Intermediate Mid. Deliberately not the guideline prose:
# the rater needs the *discriminating* feature of each band in a form short
# enough to carry in every rating prompt, and ACTFL keys its own distinctions on
# text type, time frames, and where performance breaks down — so those are what
# survive the condensing.
#
# IM1/IM2/IM3 are not ACTFL levels. ACTFL has one Intermediate Mid; OPIc splits
# it in three for the Korean market, and IM2 is where ACTFL's Intermediate Mid
# sits. Saying so is the point of these three entries: handed the bare enum, a
# rater reads them as three separate major bands and crowds its verdicts into
# the middle of the scale.
#
# Three of these entries were rewritten after measuring the rater on 1050 stored
# verdicts. IM3 was defined as "everything IM2 has, plus ..." and was never
# awarded: 0% of fluency, grammar and vocabulary verdicts, 4.9% overall, so the
# scale had one usable rung between IM2 and IH and the mass piled on IM2. IM3 now
# names features of its own that can be looked for in an answer. IH and AL say
# outright that errors are expected and do not lower them, because grammar came
# back IM1 on 60% of answers and IL on 9% while correlating with answer duration
# at -0.39 — the rater was counting errors, which is not what sets an ACTFL
# level, and a longer answer therefore scored worse than a shorter one.
LEVEL_DESCRIPTORS: dict[ActflLevel, str] = {
    ActflLevel.NL: (
        "Rehearsed words and phrases only. Can greet, give their identity and "
        "name familiar objects. Influence from other languages interferes with "
        "being understood at all."
    ),
    ActflLevel.NM: (
        "Isolated words, rehearsed phrases and short sentences drawn from "
        "contexts already learned. Stock answers to direct questions, frequent "
        "pauses hunting for vocabulary, recycles the questioner's own wording."
    ),
    ActflLevel.NH: (
        "Short and sometimes incomplete sentences, almost entirely in the "
        "present, on survival topics. Expands rehearsed material and stock "
        "phrases — which can resemble creating with the language without being "
        "it."
    ),
    ActflLevel.IL: (
        "Creates with the language, but in short sentences on concrete, "
        "predictable topics. Primarily reactive; hesitates, repeats and "
        "self-corrects often while searching for form. Generally understood "
        "despite strong influence from the first language."
    ),
    ActflLevel.IM1: (
        "Intermediate Mid, lower third. Strings sentences together on familiar "
        "topics, but the strings run two or three sentences before they break, "
        "and pauses and reformulations are frequent enough to be noticeable "
        "throughout. Stays close to concrete, well-rehearsed ground."
    ),
    ActflLevel.IM2: (
        "Intermediate Mid proper — where ACTFL's single Intermediate Mid sits. "
        "Creates with the language in strings of sentences across a variety of "
        "uncomplicated social and transactional tasks, and holds the strings "
        "across the whole answer rather than in bursts. Pauses, reformulations "
        "and self-corrections occur; the speaker is generally understood and "
        "can sometimes repair a misunderstanding."
    ),
    ActflLevel.IM3: (
        "Intermediate Mid, upper third. The strings run long and are joined: "
        "real connectors rather than a list, one topic carried across several "
        "sentences, and enough detail that the answer develops instead of "
        "restating. Tense, stress and pronunciation are steady rather than "
        "intermittent, and the flow is natural. Touches paragraph length "
        "occasionally; never holds it, and does not narrate across all major "
        "time frames."
    ),
    ActflLevel.IH: (
        "Converses with ease and confidence on routine and familiar topics; "
        "breadth of vocabulary and control reduce the need to pause. Reaches "
        "paragraph-length connected discourse and narrates or describes in all "
        "major time frames — but does not hold it, showing one or more features "
        "of breakdown: the time frame is not carried through, the paragraph "
        "collapses back into sentences, or vocabulary narrows under load. "
        "Frequent errors in complex structures are expected at this band and do "
        "not lower it."
    ),
    ActflLevel.AL: (
        "Narrates and describes in past, present and future with some control "
        "of aspect, and *sustains* paragraph-length connected discourse rather "
        "than reaching for it. Handles a complication or an unexpected turn "
        "without abandoning the task. Errors persist and do not lower this "
        "band; what it requires is that the intended message is never "
        "misrepresented."
    ),
}
