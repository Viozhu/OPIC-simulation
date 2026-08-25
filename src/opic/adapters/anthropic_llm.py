"""Writes the exam's questions and rates its answers, through the Claude API.

The same prompts, the same schemas and the same `parse_rating` filter as the
local adapter — only the transport and the model differ. That is deliberate:
the rater bench (`tools/rater_bench.py`) compares the two, and a comparison
between two prompts would say nothing about the two raters.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import anthropic

from opic.adapters import config
from opic.adapters.narrative import (
    ANALYSIS_SCHEMA,
    REWRITES_SCHEMA,
    NarrativeError,
    analysis_prompt,
    parse_analysis,
    parse_rewrites,
    rewrites_prompt,
)
from opic.adapters.llm import (
    QUESTIONS_SCHEMA,
    RATING_SCHEMA,
    RaterError,
    questions_prompt,
    rating_prompt,
    parse_rating,
)
from opic.core.metrics import AnswerMetrics
from opic.core.narrative import Narrative
from opic.core.report import Report
from opic.core.questions import Question, QuestionSlot
from opic.core.scoring import DimensionScore
from opic.core.survey import SurveyAnswers
from opic.core.transcript import Transcript


class MissingCredentials(RuntimeError):
    """No API key anywhere the client knows to look."""


# Keywords the Messages API rejects inside `output_config.format.schema`. The
# first one is measured, not guessed: sending `maxItems` on the narrative
# schema comes back as
#   400 output_config.format.schema: For 'array' type, property 'maxItems' is
#   not supported
# and the size and length bounds beside it are dropped for the same reason.
# Nothing is lost by dropping them here — every one of these is a bound the
# parser on the way back in enforces anyway, and it enforces them for both
# backends rather than only for the one whose transport happens to accept the
# keyword.
UNSUPPORTED_KEYWORDS = frozenset(
    {"minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum"}
)


def strict(schema: dict[str, Any]) -> dict[str, Any]:
    """The given schema as the Messages API will accept it.

    Two changes. `additionalProperties: false` on every object, which
    structured outputs require and Ollama's `format` does not. And every
    keyword in `UNSUPPORTED_KEYWORDS` removed, which structured outputs reject
    outright. The shared schemas in `llm.py` and `narrative.py` are written
    without either concession, so neither adapter carries the other's
    constraints.
    """
    out = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
            for keyword in UNSUPPORTED_KEYWORDS & node.keys():
                del node[keyword]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(out)
    return out


class AnthropicClient:
    """The `QuestionWriter` and `Rater` ports, over the Messages API.

    Credentials come from `API_KEY_ANTHROPIC` or `ANTHROPIC_API_KEY`; when
    neither is set the SDK is left to resolve them itself, which is how an
    `ant auth login` profile keeps working.
    """

    def __init__(
        self,
        model: str = config.ANTHROPIC_MODEL,
        max_tokens: int = config.ANTHROPIC_MAX_TOKENS,
        timeout_s: int = config.ANTHROPIC_TIMEOUT_S,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        if client is not None:
            self._client = client
            return
        key = config.anthropic_api_key()
        self._client = (
            anthropic.Anthropic(api_key=key, timeout=float(timeout_s))
            if key
            else anthropic.Anthropic(timeout=float(timeout_s))
        )
        # The SDK does not complain about missing credentials until the first
        # request. That request is made from the grading worker, after the
        # candidate has already spoken, so the check is pulled forward to here:
        # a missing key should stop the exam before it starts, not halfway
        # through it. `credentials` covers an `ant auth login` profile, which
        # is a real way to be authenticated with no key in the environment.
        if (
            self._client.api_key is None
            and self._client.auth_token is None
            and self._client.credentials is None
        ):
            raise MissingCredentials(
                "no Anthropic credentials. Put API_KEY_ANTHROPIC=... in .env "
                "(already git-ignored), or export ANTHROPIC_API_KEY, or run "
                "`ant auth login`. To grade locally instead, set OPIC_LLM=ollama."
            )

    def _generate(self, prompt: str, schema: dict[str, Any]) -> dict:
        """One request, constrained to `schema`, returned as parsed JSON.

        `effort` is never sent: Haiku 4.5 rejects it outright, and the models
        that accept it are not what this adapter is pointed at by default.
        """
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            output_config={
                "format": {"type": "json_schema", "schema": strict(schema)}
            },
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RaterError(
                f"{self._model} returned unparseable JSON: {text[:400]!r}"
            ) from exc

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
        """Judge one answer, retrying once if the rating comes back broken.

        Same bargain as the local adapter: a retry costs one more request, a
        rejected rating costs the answer.
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

    # ------------------------------------------------------- the report's prose

    def write_narrative(self, report: Report) -> Narrative:
        """The two judged halves of the report page, in two requests.

        Independent on purpose. One response carrying both the analysis and
        fifteen rewrites is one truncation away from losing everything, and the
        two failures are not equally likely — the rewrites are far more output.
        A half that fails costs its own sections and nothing else.
        """
        analysis = self._attempt_narrative(
            lambda: parse_analysis(
                self._generate(analysis_prompt(report), ANALYSIS_SCHEMA), report
            )
        )
        rewrites = self._attempt_narrative(
            lambda: parse_rewrites(
                self._generate(rewrites_prompt(report), REWRITES_SCHEMA), report
            )
        )
        if analysis is None and rewrites is None:
            raise NarrativeError(
                f"{self._model} produced neither an analysis nor a usable rewrite"
            )
        return Narrative(analysis=analysis, rewrites=rewrites or ())

    def _attempt_narrative(self, call):
        """One retry, then give up on this half and keep the other.

        Same bargain as `rate`: a retry costs one more request, and giving up
        costs a section of a page that is otherwise complete.
        """
        for _ in range(2):
            try:
                return call()
            except (NarrativeError, RaterError, ValueError, KeyError, TypeError):
                continue
        return None
