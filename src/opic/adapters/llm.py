from __future__ import annotations

import json
import urllib.request
from typing import Any

from opic.adapters import config
from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.rubric import LEVEL_DESCRIPTORS, ActflLevel, Dimension
from opic.core.scoring import DimensionScore, Evidence
from opic.core.survey import ITEMS_BY_ID, SurveyAnswers
from opic.core.transcript import Transcript


class RaterError(ValueError):
    """The model returned something this adapter cannot use."""


_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "quote": {"type": "string"},
            "issue_ko": {"type": "string"},
            "correction_en": {
                "type": "string",
                "description": (
                    "The quoted words rewritten as correct English — the "
                    "sentence the candidate should have said. Not a description "
                    "of the mistake, and never Korean."
                ),
            },
        },
        "required": ["quote", "issue_ko", "correction_en"],
    },
}

_DIMENSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "level": {"type": "string", "enum": [level.name for level in ActflLevel]},
        "comment_ko": {"type": "string"},
        "evidence": _EVIDENCE_SCHEMA,
    },
    "required": ["level", "comment_ko", "evidence"],
}

# One required key per dimension, rather than an array of five entries each
# naming its own dimension. The array form was bounded at five items but said
# nothing about which five: on real answers the model twice returned `relevance`
# twice and no `coherence`, and the whole rating had to be thrown away. Keys
# make that unrepresentable rather than merely forbidden.
RATING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {d.value: _DIMENSION_SCHEMA for d in Dimension},
    "required": [d.value for d in Dimension],
}

QUESTIONS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["questions"],
}

_TYPE_BRIEF: dict[QuestionType, str] = {
    QuestionType.SELF_INTRO: "ask the candidate to introduce themselves",
    QuestionType.DESCRIPTION: "ask them to describe their {topic}",
    QuestionType.HABIT: "ask what they normally do regarding {topic}",
    QuestionType.EXPERIENCE: "ask about a specific past experience with {topic}",
    QuestionType.ROLEPLAY_SETUP: (
        "set up a role-play about {topic}: give them a role and a concrete "
        "task to carry out in it"
    ),
    QuestionType.ROLEPLAY_FOLLOWUP: (
        "break that same {topic} role-play with an unexpected complication "
        "they have to talk their way out of"
    ),
}


def decode_response(envelope: dict, model: str) -> dict:
    """Unwrap Ollama's envelope, failing legibly when the model ignores the schema.

    Extracted from the request path so the failure is testable without an HTTP
    round trip — which is the only way this branch ever gets exercised, since a
    schema-obeying model never reaches it.
    """
    raw = envelope.get("response", "")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RaterError(
            f"{model} returned unparseable JSON: {raw[:400]!r}"
        ) from exc


# Hangul: syllables, plus the jamo blocks a model can emit on its own.
_HANGUL = (("\uac00", "\ud7a3"), ("\u1100", "\u11ff"), ("\u3130", "\u318f"))


def _bare(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum())


def is_usable_correction(correction_en: str, quote: str) -> bool:
    """Whether `correction_en` can be shown to the candidate as "say this instead".

    The field is the quoted words rewritten in English. Three violations can be
    recognised without guessing: an empty string; Korean, since the report
    renders this as an English sentence, so Hangul here is the model answering a
    different question; and a "correction" that is the quote again, which
    corrects nothing but reads on screen as though it did.

    A correction that is merely a *description* of the mistake ("the tense is
    wrong") is the same defect, but it is not separable from a legitimate
    rewrite by any rule that would not also throw good ones away. The prompt is
    what addresses that, not this function.
    """
    if not correction_en.strip():
        return False
    if any(
        low <= character <= high for character in correction_en for low, high in _HANGUL
    ):
        return False
    return _bare(correction_en) != _bare(quote)


def parse_rating(payload: dict, transcript_text: str) -> tuple[DimensionScore, ...]:
    """Turn the model's JSON into scores, dropping quotes it invented.

    A local model will occasionally attribute words to the candidate that they
    never said. Evidence that cannot be found in the transcript is discarded
    rather than shown: a fabricated quote is worse than none. Evidence whose
    correction is unusable goes the same way — see `is_usable_correction`.

    The payload is keyed by dimension, so a missing dimension is the only
    coverage failure left; naming one twice is no longer expressible.
    """
    scores: list[DimensionScore] = []
    for dimension in Dimension:
        entry = payload.get(dimension.value)
        if entry is None:
            raise RaterError(
                f"rating has no {dimension.value!r}; "
                f"expected all of {[d.value for d in Dimension]}"
            )
        for field in ("level", "comment_ko"):
            if field not in entry:
                raise ValueError(f"rating entry {dimension.value!r} is missing {field!r}")
        try:
            level = ActflLevel[entry["level"]]
        except KeyError as exc:
            raise ValueError(f"unknown level {entry['level']!r}") from exc

        evidence = tuple(
            Evidence(
                quote=e["quote"],
                issue_ko=e["issue_ko"],
                correction_en=e["correction_en"],
            )
            for e in entry.get("evidence", ())
            if e["quote"] in transcript_text
            and is_usable_correction(e["correction_en"], e["quote"])
        )
        scores.append(
            DimensionScore(
                dimension=dimension,
                level=level,
                comment_ko=entry["comment_ko"],
                evidence=evidence,
            )
        )
    return tuple(scores)


def rating_prompt(
    question: Question,
    transcript: Transcript,
    metrics: AnswerMetrics,
) -> str:
    """What the rater is asked. Module level so a test can read it.

    The `correction_en` sentence is load-bearing: without it the model filled
    that field with an English description of the mistake instead of the fix,
    on roughly a quarter of the evidence in a real graded exam.

    The band table is load-bearing for a different reason. Before it, the only
    thing defining a level anywhere in the request was the schema's bare enum,
    and the rater was left to supply the scale from its own prior. Across the
    three real graded exams in `data/sessions`, 171 of 225 verdicts — 76% —
    landed on IM1 or IM2, and on the two strongest 81% and 84% did. That is a
    rater consistent about a narrow middle rather than one that discriminates. `LEVEL_DESCRIPTORS` and the sustained-performance rule
    below are what ACTFL rates on, stated where the rater can see them.
    """
    bands = "\n".join(
        f"  {level.name} — {LEVEL_DESCRIPTORS[level]}" for level in ActflLevel
    )
    return (
        "You are an OPIc rater. Evaluate ONE spoken answer.\n\n"
        f"QUESTION (type: {question.slot.qtype.value}): {question.text_en}\n\n"
        "TRANSCRIPT (verbatim, errors preserved — do NOT assume typos):\n"
        f"{transcript.text}\n\n"
        "OBJECTIVE METRICS (already computed — never recompute or invent these):\n"
        f"words_per_minute: {metrics.words_per_minute:.0f}\n"
        f"pause_ratio: {metrics.pause_ratio:.2f}\n"
        f"mean_utterance_length: {metrics.mean_utterance_length:.1f}\n"
        f"type_token_ratio: {metrics.type_token_ratio:.2f}\n\n"
        "BANDS, lowest to highest:\n"
        f"{bands}\n\n"
        "Rate the level this answer SUSTAINS — not its best moment, and not its "
        "single worst error. A band is earned by performance held across the "
        "whole answer: an answer that reaches higher once and cannot hold it "
        "belongs in the lower band, and an answer that holds a band throughout "
        "belongs in it even when one sentence slips.\n\n"
        "IM1, IM2 and IM3 are thirds of ACTFL's single Intermediate Mid, not "
        "three separate major bands — the distance from IM1 to IM3 is not the "
        "distance from IL to IH. The whole scale is available; use it, and do "
        "not settle in the middle of it by default.\n\n"
        "Read each band through the dimension being scored: for grammar, what "
        "it says about accuracy and time frames; for fluency, about pauses and "
        "reformulations; for vocabulary, about breadth; for coherence, about "
        "text type — words, sentences, strings of sentences, or paragraphs; for "
        "relevance, whether the answer performs the task the question set.\n\n"
        "Rate every dimension. comment_ko and issue_ko MUST be natural Korean. "
        "Every quote MUST appear verbatim in the transcript. Keep each comment "
        "to one sentence and give at most one piece of evidence per dimension.\n\n"
        "correction_en MUST be the quoted words rewritten as correct English — "
        "the exact sentence the candidate should have said instead. It is not a "
        "description of the mistake, not a comment about the answer, and never "
        "Korean. Write the replacement itself.\n"
        "  quote: \"we take a bath there\"\n"
        "  correction_en: \"we went swimming there\"   (correct: the words to say)\n"
        "  correction_en: \"the verb tense is wrong\"  (WRONG: describes it)\n"
        "Never put the question itself, or an answer you made up, in that field."
    )


ROLEPLAY_BRIEF = """The last two items are one role-play and belong together: the
second happens inside the situation the first sets up, so write them as a pair.

Item {setup} sets the scene. Give the candidate a role and one concrete task
inside it — call the place, ask the person three or four questions, arrange the
thing. Address them as "you".

Item {complication} is the complication, and it is the only item that may run
to three or four sentences. Put them back in that same situation and break it:
something has gone wrong that they did not cause and could not have foreseen.
State what went wrong concretely — who tells them, and what it means for them
right now — then ask them to explain the problem to the person in front of them
and propose two specific solutions. Present tense, as if it is happening.

This is the shape, for a role-play that had been about changing a hotel booking:

  "You arrive at the resort on your newly changed dates, and the front desk
  staff looks up your reservation, looks very confused, and tells you that due
  to a major system glitch they are completely overbooked and have no record of
  your modification — and there are no empty rooms left in the entire building.
  Explain the problem clearly to them and propose two concrete solutions for
  how they can fix this for you."

Write your own situation for the topic at hand. Do not reuse the hotel."""


def _roleplay_brief(blueprint: tuple[QuestionSlot, ...]) -> str:
    """The extra instructions for the role-play pair, when the exam has one.

    The complication is the one question on this exam that tests what AL is
    actually rated on — "handles a complication or an unexpected turn" — and
    "continue that role-play" did not ask for one: it produced a second
    question about the same topic, which the candidate answered the same way
    they answered the first. Asking for the turn is what makes the last answer
    a different measurement from the one before it.
    """
    numbers = {
        slot.qtype: slot.index + 1
        for slot in blueprint
        if slot.qtype in (QuestionType.ROLEPLAY_SETUP, QuestionType.ROLEPLAY_FOLLOWUP)
    }
    if len(numbers) != 2:
        return ""
    return "\n\n" + ROLEPLAY_BRIEF.format(
        setup=numbers[QuestionType.ROLEPLAY_SETUP],
        complication=numbers[QuestionType.ROLEPLAY_FOLLOWUP],
    )


def questions_prompt(blueprint: tuple[QuestionSlot, ...]) -> str:
    """What the question writer is asked. Module level so both adapters share it.

    The blueprint already fixes the type, topic and target level of every slot;
    the model is only asked for the English wording.
    """
    lines = []
    for slot in blueprint:
        topic = ITEMS_BY_ID[slot.topic_id].label_en if slot.topic_id else "themselves"
        brief = _TYPE_BRIEF[slot.qtype].format(topic=topic)
        lines.append(f"{slot.index + 1}. {brief}, at {slot.target.name} level")

    return (
        "You are writing questions for an OPIc English speaking test.\n"
        "Write one spoken-English question for each item below. Each must be "
        "one or two sentences — except the last role-play item, see below — "
        "natural, and answerable in 90 seconds.\n"
        "Return them in order, exactly one per item.\n\n"
        + "\n".join(lines)
        + _roleplay_brief(blueprint)
    )


class OllamaClient:
    """Writes the exam's questions and rates its answers, over Ollama's HTTP API.

    Uses `urllib` rather than an HTTP library so the project keeps exactly one
    runtime dependency.
    """

    def __init__(
        self,
        url: str = config.OLLAMA_URL,
        model: str = config.OLLAMA_MODEL,
        timeout_s: int = config.OLLAMA_TIMEOUT_S,
    ) -> None:
        self._url = url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s

    def _generate(self, prompt: str, schema: dict[str, Any]) -> dict:
        body = json.dumps(
            {
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "format": schema,
                "options": {"temperature": 0.2},
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
            envelope = json.loads(response.read())
        return decode_response(envelope, self._model)

    def write(
        self, answers: SurveyAnswers, blueprint: tuple[QuestionSlot, ...]
    ) -> tuple[Question, ...]:
        payload = self._generate(questions_prompt(blueprint), QUESTIONS_SCHEMA)
        texts = payload["questions"]
        if len(texts) != len(blueprint):
            raise ValueError(
                f"model returned {len(texts)} questions for {len(blueprint)} slots"
            )
        return tuple(
            Question(slot=slot, text_en=text.strip())
            for slot, text in zip(blueprint, texts, strict=True)
        )

    def rate(
        self,
        question: Question,
        transcript: Transcript,
        metrics: AnswerMetrics,
    ) -> tuple[DimensionScore, ...]:
        """Judge one answer, retrying once if the model returns a broken rating.

        A rating costs minutes, but a rejected one costs the whole session, so a
        single retry is far cheaper than the alternative.
        """
        try:
            return self._rate_once(question, transcript, metrics)
        except RaterError:
            return self._rate_once(question, transcript, metrics)

    def _rate_once(
        self,
        question: Question,
        transcript: Transcript,
        metrics: AnswerMetrics,
    ) -> tuple[DimensionScore, ...]:
        prompt = rating_prompt(question, transcript, metrics)
        return parse_rating(self._generate(prompt, RATING_SCHEMA), transcript.text)
