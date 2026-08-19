from __future__ import annotations

import json
from pathlib import Path

import pytest

from opic.adapters.llm import (
    QUESTIONS_SCHEMA,
    RATING_SCHEMA,
    OllamaClient,
    RaterError,
    decode_response,
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


def full_payload(dimension="grammar", level="IM2", quote="we take a bath"):
    """`payload()`'s entry, plus filler for the dimensions it leaves out.

    `parse_rating` refuses a rating that does not cover every dimension exactly
    once, so any test asserting on a *result* has to send a complete one.
    """
    entry = payload(dimension=dimension, level=level, quote=quote)["dimensions"][0]
    filler = [
        {
            "dimension": d.value,
            "level": "IM2",
            "comment_ko": "설명",
            "evidence": [],
        }
        for d in Dimension
        if d is not Dimension.GRAMMAR
    ]
    return {"dimensions": [entry, *filler]}


def test_the_client_satisfies_both_ports():
    client = OllamaClient()
    assert isinstance(client, Rater)
    assert isinstance(client, QuestionWriter)


def test_a_rating_becomes_dimension_scores():
    scores = parse_rating(full_payload(), SAID)
    assert len(scores) == len(Dimension)
    assert scores[0].dimension is Dimension.GRAMMAR
    assert scores[0].level is ActflLevel.IM2
    assert scores[0].comment_ko
    assert scores[0].evidence[0].correction_en == "we took a bath"


def test_an_invented_quote_is_discarded():
    scores = parse_rating(full_payload(quote="I climbed Mount Everest"), SAID)
    assert scores[0].evidence == ()


def test_a_real_quote_survives_alongside_an_invented_one():
    p = full_payload()
    p["dimensions"][0]["evidence"].append(
        {"quote": "never said this", "issue_ko": "x", "correction_en": "y"}
    )
    scores = parse_rating(p, SAID)
    assert len(scores[0].evidence) == 1
    assert scores[0].evidence[0].quote == "we take a bath"


def test_an_unknown_dimension_is_refused():
    with pytest.raises(ValueError):
        parse_rating(full_payload(dimension="charisma"), SAID)


def test_an_unknown_level_is_refused():
    with pytest.raises(ValueError):
        parse_rating(full_payload(level="SUPERB"), SAID)


def test_the_rating_schema_demands_every_dimension():
    dims = RATING_SCHEMA["properties"]["dimensions"]
    assert dims["minItems"] == len(Dimension)
    assert dims["maxItems"] == len(Dimension)
    allowed = dims["items"]["properties"]["dimension"]["enum"]
    assert set(allowed) == {d.value for d in Dimension}


def test_the_questions_schema_asks_for_strings():
    assert QUESTIONS_SCHEMA["properties"]["questions"]["items"]["type"] == "string"


def test_a_well_formed_envelope_is_unwrapped():
    assert decode_response({"response": '{"ok": true}'}, "qwen3:8b") == {"ok": True}


def test_unparseable_model_output_names_the_model_and_shows_what_it_said():
    with pytest.raises(RaterError) as caught:
        decode_response({"response": "I think the answer is IM2"}, "qwen3:8b")
    assert "qwen3:8b" in str(caught.value)
    assert "I think the answer is IM2" in str(caught.value)


def test_a_rating_payload_without_dimensions_is_refused():
    with pytest.raises(ValueError):
        parse_rating({}, SAID)


def test_a_rating_entry_missing_a_field_names_that_field():
    broken = full_payload()
    del broken["dimensions"][0]["comment_ko"]
    with pytest.raises(ValueError) as caught:
        parse_rating(broken, SAID)
    assert "comment_ko" in str(caught.value)


def test_a_duplicated_dimension_is_refused():
    p = payload()
    p["dimensions"].append(payload()["dimensions"][0])
    with pytest.raises(RaterError, match="grammar"):
        parse_rating(p, SAID)


def test_a_rating_missing_a_dimension_is_refused():
    p = payload()
    with pytest.raises(RaterError):
        parse_rating(p, SAID)


def test_a_complete_rating_is_accepted():
    p = {"dimensions": [
        {
            "dimension": d.value,
            "level": "IM2",
            "comment_ko": "설명",
            "evidence": [],
        }
        for d in Dimension
    ]}
    assert len(parse_rating(p, SAID)) == len(Dimension)


def test_rater_error_is_a_value_error():
    assert issubclass(RaterError, ValueError)
