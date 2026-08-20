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
from opic.adapters.llm import (
    QUESTIONS_SCHEMA,
    RATING_SCHEMA,
    RaterError,
    questions_prompt,
    rating_prompt,
    parse_rating,
)
from opic.core.metrics import AnswerMetrics
from opic.core.questions import Question, QuestionSlot
from opic.core.scoring import DimensionScore
from opic.core.survey import SurveyAnswers
from opic.core.transcript import Transcript


class MissingCredentials(RuntimeError):
    """No API key anywhere the client knows to look."""


def strict(schema: dict[str, Any]) -> dict[str, Any]:
    """The given schema with `additionalProperties: false` on every object.

    Structured outputs require it and Ollama's `format` does not, so the shared
    schemas in `llm.py` are written without it and this adds it on the way out.
    Keeping it here rather than in the schema means neither adapter has to carry
    the other's constraints.
    """
    out = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
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
