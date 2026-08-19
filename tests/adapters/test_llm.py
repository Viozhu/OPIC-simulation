from __future__ import annotations

import json
from pathlib import Path

import pytest

from opic.adapters.llm import (
    QUESTIONS_SCHEMA,
    RATING_SCHEMA,
    OllamaClient,
    parse_rating,
)
from opic.core.ports import QuestionWriter, Rater
from opic.core.rubric import ActflLevel, Dimension

SAID = "I go to the beach and we take a bath there"


def payload(dimension="grammar", level="IM2", quote="we take a bath"):
    return {
        "dimensions": [
            {
                "dimension": dimension,
                "level": level,
                "comment_ko": "문법 오류가 있습니다.",
                "evidence": [
                    {
                        "quote": quote,
                        "issue_ko": "시제가 잘못되었습니다.",
                        "correction_en": "we took a bath",
                    }
                ],
            }
        ]
    }


def test_the_client_satisfies_both_ports():
    client = OllamaClient()
    assert isinstance(client, Rater)
    assert isinstance(client, QuestionWriter)


def test_a_rating_becomes_dimension_scores():
    scores = parse_rating(payload(), SAID)
    assert len(scores) == 1
    assert scores[0].dimension is Dimension.GRAMMAR
    assert scores[0].level is ActflLevel.IM2
    assert scores[0].comment_ko
    assert scores[0].evidence[0].correction_en == "we took a bath"


def test_an_invented_quote_is_discarded():
    scores = parse_rating(payload(quote="I climbed Mount Everest"), SAID)
    assert scores[0].evidence == ()


def test_a_real_quote_survives_alongside_an_invented_one():
    p = payload()
    p["dimensions"][0]["evidence"].append(
        {"quote": "never said this", "issue_ko": "x", "correction_en": "y"}
    )
    scores = parse_rating(p, SAID)
    assert len(scores[0].evidence) == 1
    assert scores[0].evidence[0].quote == "we take a bath"


def test_an_unknown_dimension_is_refused():
    with pytest.raises(ValueError):
        parse_rating(payload(dimension="charisma"), SAID)


def test_an_unknown_level_is_refused():
    with pytest.raises(ValueError):
        parse_rating(payload(level="SUPERB"), SAID)


def test_the_rating_schema_demands_every_dimension():
    dims = RATING_SCHEMA["properties"]["dimensions"]
    assert dims["minItems"] == len(Dimension)
    assert dims["maxItems"] == len(Dimension)
    allowed = dims["items"]["properties"]["dimension"]["enum"]
    assert set(allowed) == {d.value for d in Dimension}


def test_the_questions_schema_asks_for_strings():
    assert QUESTIONS_SCHEMA["properties"]["questions"]["items"]["type"] == "string"
