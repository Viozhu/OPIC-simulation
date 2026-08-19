from __future__ import annotations

import json
import urllib.request
from typing import Any

from opic.adapters import config
from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot, QuestionType
from opic.core.rubric import ActflLevel, Dimension
from opic.core.scoring import DimensionScore, Evidence
from opic.core.survey import ITEMS_BY_ID, SurveyAnswers
from opic.core.transcript import Transcript


class RaterError(ValueError):
    """The model returned something this adapter cannot use."""


RATING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "dimensions": {
            "type": "array",
            "minItems": len(Dimension),
            "maxItems": len(Dimension),
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {
                        "type": "string",
                        "enum": [d.value for d in Dimension],
                    },
                    "level": {
                        "type": "string",
                        "enum": [level.name for level in ActflLevel],
                    },
                    "comment_ko": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "quote": {"type": "string"},
                                "issue_ko": {"type": "string"},
                                "correction_en": {"type": "string"},
                            },
                            "required": ["quote", "issue_ko", "correction_en"],
                        },
                    },
                },
                "required": ["dimension", "level", "comment_ko", "evidence"],
            },
        }
    },
    "required": ["dimensions"],
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
    QuestionType.ROLEPLAY_SETUP: "set up a role-play situation about {topic}",
    QuestionType.ROLEPLAY_FOLLOWUP: "continue that role-play about {topic}",
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


def parse_rating(payload: dict, transcript_text: str) -> tuple[DimensionScore, ...]:
    """Turn the model's JSON into scores, dropping quotes it invented.

    A local model will occasionally attribute words to the candidate that they
    never said. Evidence that cannot be found in the transcript is discarded
    rather than shown: a fabricated quote is worse than none.
    """
    if "dimensions" not in payload:
        raise ValueError("rating payload has no 'dimensions'")

    scores: list[DimensionScore] = []
    for item in payload["dimensions"]:
        for field in ("dimension", "level", "comment_ko"):
            if field not in item:
                raise ValueError(f"rating entry is missing {field!r}")
        try:
            dimension = Dimension(item["dimension"])
        except ValueError as exc:
            raise ValueError(f"unknown dimension {item['dimension']!r}") from exc
        try:
            level = ActflLevel[item["level"]]
        except KeyError as exc:
            raise ValueError(f"unknown level {item['level']!r}") from exc

        evidence = tuple(
            Evidence(
                quote=e["quote"],
                issue_ko=e["issue_ko"],
                correction_en=e["correction_en"],
            )
            for e in item.get("evidence", ())
            if e["quote"] in transcript_text
        )
        scores.append(
            DimensionScore(
                dimension=dimension,
                level=level,
                comment_ko=item["comment_ko"],
                evidence=evidence,
            )
        )

    covered = [score.dimension for score in scores]
    if sorted(d.value for d in covered) != sorted(d.value for d in Dimension):
        raise RaterError(
            f"rating covered {[d.value for d in covered]}, "
            f"expected exactly {[d.value for d in Dimension]}"
        )
    return tuple(scores)


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
        lines = []
        for slot in blueprint:
            topic = (
                ITEMS_BY_ID[slot.topic_id].label_en if slot.topic_id else "themselves"
            )
            brief = _TYPE_BRIEF[slot.qtype].format(topic=topic)
            lines.append(f"{slot.index + 1}. {brief}, at {slot.target.name} level")

        prompt = (
            "You are writing questions for an OPIc English speaking test.\n"
            "Write one spoken-English question for each item below. Each must be "
            "one or two sentences, natural, and answerable in 90 seconds.\n"
            "Return them in order, exactly one per item.\n\n"
            + "\n".join(lines)
        )
        payload = self._generate(prompt, QUESTIONS_SCHEMA)
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
        prompt = (
            "You are an OPIc rater. Evaluate ONE spoken answer.\n\n"
            f"QUESTION (type: {question.slot.qtype.value}): {question.text_en}\n\n"
            "TRANSCRIPT (verbatim, errors preserved — do NOT assume typos):\n"
            f"{transcript.text}\n\n"
            "OBJECTIVE METRICS (already computed — never recompute or invent these):\n"
            f"words_per_minute: {metrics.words_per_minute:.0f}\n"
            f"pause_ratio: {metrics.pause_ratio:.2f}\n"
            f"mean_utterance_length: {metrics.mean_utterance_length:.1f}\n"
            f"type_token_ratio: {metrics.type_token_ratio:.2f}\n\n"
            "Rate every dimension. comment_ko and issue_ko MUST be natural Korean. "
            "Every quote MUST appear verbatim in the transcript. Keep each comment "
            "to one sentence and give at most one piece of evidence per dimension."
        )
        return parse_rating(self._generate(prompt, RATING_SCHEMA), transcript.text)
