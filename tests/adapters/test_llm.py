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


def test_the_client_satisfies_both_ports():
    client = OllamaClient()
    assert isinstance(client, Rater)
    assert isinstance(client, QuestionWriter)


def test_a_rating_becomes_dimension_scores():
    scores = parse_rating(keyed_payload(), SAID)
    assert [s.dimension for s in scores] == list(Dimension)
    grammar = next(s for s in scores if s.dimension is Dimension.GRAMMAR)
    assert grammar.level is ActflLevel.IM2
    assert grammar.comment_ko
    assert grammar.evidence[0].correction_en == "we took a bath"


def test_an_invented_quote_is_discarded():
    scores = parse_rating(keyed_payload(quote="I climbed Mount Everest"), SAID)
    assert all(s.evidence == () for s in scores)


def test_a_real_quote_survives_alongside_an_invented_one():
    p = keyed_payload()
    p["grammar"]["evidence"].append(
        {"quote": "never said this", "issue_ko": "x", "correction_en": "y"}
    )
    grammar = next(s for s in parse_rating(p, SAID) if s.dimension is Dimension.GRAMMAR)
    assert len(grammar.evidence) == 1
    assert grammar.evidence[0].quote == "we take a bath"


def test_an_unknown_level_is_refused():
    with pytest.raises(ValueError):
        parse_rating(keyed_payload(level="SUPERB"), SAID)


def test_the_questions_schema_asks_for_strings():
    assert QUESTIONS_SCHEMA["properties"]["questions"]["items"]["type"] == "string"


def test_a_well_formed_envelope_is_unwrapped():
    assert decode_response({"response": '{"ok": true}'}, "qwen3:8b") == {"ok": True}


def test_unparseable_model_output_names_the_model_and_shows_what_it_said():
    with pytest.raises(RaterError) as caught:
        decode_response({"response": "I think the answer is IM2"}, "qwen3:8b")
    assert "qwen3:8b" in str(caught.value)
    assert "I think the answer is IM2" in str(caught.value)


def test_an_empty_rating_payload_is_refused():
    with pytest.raises(RaterError):
        parse_rating({}, SAID)


def test_a_rating_entry_missing_a_field_names_that_field_and_its_dimension():
    broken = keyed_payload()
    del broken["grammar"]["comment_ko"]
    with pytest.raises(ValueError) as caught:
        parse_rating(broken, SAID)
    assert "comment_ko" in str(caught.value)
    assert "grammar" in str(caught.value)


def test_a_rating_with_no_evidence_at_all_is_still_a_rating():
    p = {
        d.value: {"level": "IM2", "comment_ko": "설명", "evidence": []}
        for d in Dimension
    }
    assert len(parse_rating(p, SAID)) == len(Dimension)


def test_rater_error_is_a_value_error():
    assert issubclass(RaterError, ValueError)


# `correction_en` is the sentence the candidate should have said. The prompt did
# not say so, and on a real graded exam roughly a quarter of the corrections came
# back as English descriptions of the problem instead. The prompt now defines the
# field; these pin the two violations that can be recognised without guessing.


def test_a_blank_correction_discards_its_evidence():
    p = keyed_payload()
    p["grammar"]["evidence"][0]["correction_en"] = "   "
    assert all(s.evidence == () for s in parse_rating(p, SAID))


def test_a_korean_correction_discards_its_evidence():
    p = keyed_payload()
    p["grammar"]["evidence"][0]["correction_en"] = "과거형을 사용해야 합니다"
    assert all(s.evidence == () for s in parse_rating(p, SAID))


def test_a_good_correction_survives_beside_a_korean_one():
    p = keyed_payload()
    p["grammar"]["evidence"].append(
        {
            "quote": "I go to the beach",
            "issue_ko": "시제가 잘못되었습니다.",
            "correction_en": "한국어로 쓴 교정",
        }
    )
    evidence = next(
        s for s in parse_rating(p, SAID) if s.dimension is Dimension.GRAMMAR
    ).evidence
    assert len(evidence) == 1
    assert evidence[0].correction_en == "we took a bath"


def test_the_rating_schema_says_what_a_correction_is():
    field = RATING_SCHEMA["properties"]["grammar"]["properties"]["evidence"]["items"][
        "properties"
    ]["correction_en"]
    assert field.get("description", "").strip()


def _a_rating_prompt() -> str:
    """The prompt the rater actually sends, over a small but real answer."""
    from opic.adapters.llm import rating_prompt
    from opic.core.metrics import AnswerMetrics
    from opic.core.questions import Question, QuestionSlot, QuestionType
    from opic.core.transcript import Span, Transcript, Word

    question = Question(
        slot=QuestionSlot(
            index=0,
            qtype=QuestionType.DESCRIPTION,
            topic_id="movies",
            combo_id=0,
            advanced=False,
            target=ActflLevel.IM2,
        ),
        text_en="Tell me about a film you liked.",
    )
    transcript = Transcript(
        text=SAID,
        words=tuple(Word(w, i * 0.4, i * 0.4 + 0.3, 0.9) for i, w in enumerate(SAID.split())),
        speech_spans=(Span(0.0, 4.0),),
        duration_s=10.0,
    )
    metrics = AnswerMetrics(
        duration_s=10.0,
        word_count=10,
        words_per_minute=60.0,
        pause_ratio=0.1,
        type_token_ratio=0.9,
        mean_utterance_length=10.0,
        mean_confidence=0.9,
        low_confidence_rate=0.0,
    )

    return rating_prompt(question, transcript, metrics)


def test_the_rating_prompt_carries_every_band_and_its_descriptor():
    """Without this the scale is only the schema's enum.

    That was the state in which 171 of 225 verdicts across three real graded
    exams — 76% — landed on IM1 or IM2: the rater had nine names and no
    definitions, so it supplied the scale itself and settled in the middle.
    """
    from opic.core.rubric import LEVEL_DESCRIPTORS, ActflLevel

    prompt = _a_rating_prompt()
    for level in ActflLevel:
        assert level.name in prompt
        assert LEVEL_DESCRIPTORS[level] in prompt


def test_the_rating_prompt_asks_for_the_sustained_level():
    """ACTFL rates the level a sample holds, not the level it touches once."""
    prompt = _a_rating_prompt()
    assert "SUSTAINS" in prompt
    assert "best moment" in prompt


def test_the_rating_prompt_says_the_im_bands_are_thirds_of_one_band():
    """IM1/IM2/IM3 are OPIc's split of ACTFL's single Intermediate Mid.

    Read as three separate major bands they widen the middle of the scale,
    which is exactly where the ratings were crowding.
    """
    prompt = _a_rating_prompt()
    assert "thirds of ACTFL's single Intermediate Mid" in prompt


def test_the_rating_prompt_defines_the_correction_field():
    prompt = _a_rating_prompt()
    assert "correction_en" in prompt
    assert "rewritten" in prompt.lower()
    assert "not a description" in prompt.lower()


def keyed_payload(level="IM2", quote="we take a bath"):
    body = {
        d.value: {"level": "IM2", "comment_ko": "설명", "evidence": []}
        for d in Dimension
    }
    body["grammar"] = {
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
    return body


def test_a_rating_keyed_by_dimension_becomes_scores():
    scores = parse_rating(keyed_payload(), SAID)
    assert len(scores) == len(Dimension)
    by_dimension = {s.dimension: s for s in scores}
    assert by_dimension[Dimension.GRAMMAR].level is ActflLevel.IM2
    assert by_dimension[Dimension.GRAMMAR].evidence[0].correction_en == "we took a bath"


def test_a_rating_missing_a_dimension_key_is_refused():
    p = keyed_payload()
    del p["coherence"]
    with pytest.raises(RaterError, match="coherence"):
        parse_rating(p, SAID)


def test_the_rating_schema_requires_every_dimension_as_its_own_key():
    assert RATING_SCHEMA["type"] == "object"
    assert set(RATING_SCHEMA["required"]) == {d.value for d in Dimension}
    assert set(RATING_SCHEMA["properties"]) == {d.value for d in Dimension}
    entry = RATING_SCHEMA["properties"]["grammar"]
    assert set(entry["required"]) == {"level", "comment_ko", "evidence"}
    assert "dimension" not in entry["properties"]


def test_the_rating_prompt_forbids_echoing_the_question():
    """The other way the field went wrong, seen on real answers.

    When the answer was about something else, the model put the question itself
    — or an on-topic answer it invented — where the correction belongs.
    """
    prompt = _a_rating_prompt().lower()
    assert "never put the question itself" in prompt
    assert "made up" in prompt


def test_a_correction_identical_to_its_quote_discards_the_evidence():
    """Seen on a real answer: quote and correction were the same sentence.

    The report renders that as "→ <the words you already said>", which corrects
    nothing. Unlike a description, this one is decidable without guessing.
    """
    p = keyed_payload()
    p["grammar"]["evidence"][0]["correction_en"] = "we take a bath"
    assert all(s.evidence == () for s in parse_rating(p, SAID))


def test_a_correction_differing_only_in_case_and_spacing_is_still_a_no_op():
    p = keyed_payload()
    p["grammar"]["evidence"][0]["correction_en"] = "  We take a bath.  "
    assert all(s.evidence == () for s in parse_rating(p, SAID))
