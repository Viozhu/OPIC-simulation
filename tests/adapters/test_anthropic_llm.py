"""The Claude-backed adapter, exercised without touching the network.

Every test here drives a fake `messages.create`, so what is under test is the
adapter's own work: the schema it sends, the credentials it resolves, and what
it does with a reply. The model's judgement is not testable here and is not
what these pin.
"""

from __future__ import annotations

import json

import pytest

from opic.adapters import config, make_llm_client
from opic.adapters.anthropic_llm import AnthropicClient, MissingCredentials, strict
from opic.adapters.llm import QUESTIONS_SCHEMA, RATING_SCHEMA, OllamaClient, RaterError
from opic.core.ports import QuestionWriter, Rater
from opic.core.questions import QuestionSlot, QuestionType
from opic.core.rubric import ActflLevel, Dimension

# The same payload the local adapter is tested against, so the two adapters
# are pinned to one shape of rating rather than to two.
from adapters.test_llm import SAID, keyed_payload


class FakeBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class FakeMessages:
    """Records every request and replies with whatever it was handed."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if self.replies else "{}"

        class Response:
            content = [FakeBlock(reply)]

        return Response()


class FakeAnthropic:
    def __init__(self, *replies: str) -> None:
        self.messages = FakeMessages(list(replies))


def a_client(*replies: str) -> tuple[AnthropicClient, FakeAnthropic]:
    fake = FakeAnthropic(*replies)
    return AnthropicClient(client=fake), fake


def test_the_client_satisfies_both_ports():
    client, _ = a_client()
    assert isinstance(client, Rater)
    assert isinstance(client, QuestionWriter)


def test_both_adapters_satisfy_the_same_ports():
    """The point of the switch: nothing downstream can tell them apart."""
    for client in (OllamaClient(), a_client()[0]):
        assert isinstance(client, Rater)
        assert isinstance(client, QuestionWriter)


# ---------------------------------------------------------------- the schema


def test_strict_marks_every_object_closed():
    out = strict(RATING_SCHEMA)
    assert out["additionalProperties"] is False
    assert out["properties"]["grammar"]["additionalProperties"] is False
    evidence = out["properties"]["grammar"]["properties"]["evidence"]
    assert evidence["items"]["additionalProperties"] is False


def test_strict_leaves_the_shared_schema_alone():
    """`llm.py`'s schemas are sent to Ollama too, which does not want this."""
    strict(RATING_SCHEMA)
    assert "additionalProperties" not in RATING_SCHEMA


def test_a_rating_request_is_constrained_by_the_rating_schema():
    client, fake = a_client(json.dumps(keyed_payload()))
    client.rate(*_a_rated_answer())
    sent = fake.messages.calls[0]["output_config"]["format"]
    assert sent["type"] == "json_schema"
    assert set(sent["schema"]["required"]) == {d.value for d in Dimension}


def test_no_effort_is_sent():
    """Haiku 4.5 rejects `output_config.effort` outright."""
    client, fake = a_client(json.dumps(keyed_payload()))
    client.rate(*_a_rated_answer())
    assert "effort" not in fake.messages.calls[0]["output_config"]


# ---------------------------------------------------------------- the answers


def test_a_rating_becomes_dimension_scores():
    client, _ = a_client(json.dumps(keyed_payload()))
    scores = client.rate(*_a_rated_answer())
    assert [s.dimension for s in scores] == list(Dimension)
    grammar = next(s for s in scores if s.dimension is Dimension.GRAMMAR)
    assert grammar.level is ActflLevel.IM2


def test_a_broken_rating_is_retried_once_and_then_succeeds():
    client, fake = a_client("not json at all", json.dumps(keyed_payload()))
    scores = client.rate(*_a_rated_answer())
    assert len(fake.messages.calls) == 2
    assert len(scores) == len(Dimension)


def test_a_rating_broken_twice_raises_and_names_the_model():
    client, _ = a_client("nope", "still nope")
    with pytest.raises(RaterError, match="claude-haiku-4-5"):
        client.rate(*_a_rated_answer())


def test_questions_come_back_one_per_slot():
    blueprint = _a_blueprint()
    reply = json.dumps({"questions": ["Tell me about your job.", "What did you do?"]})
    client, fake = a_client(reply)
    questions = client.write(None, blueprint)
    assert [q.text_en for q in questions] == [
        "Tell me about your job.",
        "What did you do?",
    ]
    assert [q.slot for q in questions] == list(blueprint)
    assert (
        fake.messages.calls[0]["output_config"]["format"]["schema"]["required"]
        == QUESTIONS_SCHEMA["required"]
    )


def test_the_wrong_number_of_questions_is_refused():
    client, _ = a_client(json.dumps({"questions": ["only one"]}))
    with pytest.raises(ValueError, match="1 questions for 2 slots"):
        client.write(None, _a_blueprint())


# ------------------------------------------------------------- the credentials


def test_the_project_key_name_is_accepted(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY_ANTHROPIC", "sk-from-the-project")
    assert config.anthropic_api_key() == "sk-from-the-project"


def test_the_sdk_key_name_is_accepted_too(monkeypatch):
    monkeypatch.delenv("API_KEY_ANTHROPIC", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-the-sdk")
    assert config.anthropic_api_key() == "sk-from-the-sdk"


def test_no_key_anywhere_is_not_an_error(monkeypatch):
    """An `ant auth login` profile is credentials the SDK finds on its own."""
    for name in config.API_KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert config.anthropic_api_key() is None


def test_an_env_file_reaches_a_process_that_exported_nothing(monkeypatch, tmp_path):
    for name in config.API_KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("# a comment\n\nAPI_KEY_ANTHROPIC='sk-from-the-file'\n")
    config.load_env_file(env)
    assert config.anthropic_api_key() == "sk-from-the-file"


def test_an_exported_key_beats_the_env_file(monkeypatch, tmp_path):
    """Otherwise a stale `.env` silently overrides the key given for this run."""
    monkeypatch.setenv("API_KEY_ANTHROPIC", "sk-exported")
    env = tmp_path / ".env"
    env.write_text("API_KEY_ANTHROPIC=sk-stale\n")
    config.load_env_file(env)
    assert config.anthropic_api_key() == "sk-exported"


def test_a_missing_env_file_is_not_an_error(tmp_path):
    config.load_env_file(tmp_path / "nothing-here")


def test_the_env_file_is_found_from_a_subdirectory(monkeypatch, tmp_path):
    """`.env` sits at the project root and the process does not always start there.

    A git worktree, a `cd` into `src/`, an editor's terminal — any of them means
    `cwd/.env` does not exist. Before this, that silently fell through to
    whatever `ANTHROPIC_API_KEY` happened to be exported, which is how a stale
    key produced a 401 while the good one sat unread at the root.
    """
    for name in config.API_KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("API_KEY_ANTHROPIC=sk-at-the-root\n")
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)

    config.load_env_file()

    assert config.anthropic_api_key() == "sk-at-the-root"


def test_a_linked_worktree_reads_the_main_checkout_s_env(monkeypatch, tmp_path):
    """A worktree is the same project, and `.env` is git-ignored so it is never
    copied into one. Stopping at the worktree's own `pyproject.toml` would stop
    one directory short of the only `.env` that exists — which is exactly the
    failure this whole function is here to prevent, just relocated."""
    for name in config.API_KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    main = tmp_path / "project"
    (main / ".git" / "worktrees" / "feature").mkdir(parents=True)
    (main / "pyproject.toml").write_text("[project]\nname='x'\n")
    (main / ".env").write_text("API_KEY_ANTHROPIC=sk-from-the-main-checkout\n")

    tree = tmp_path / "elsewhere" / "feature"
    tree.mkdir(parents=True)
    (tree / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tree / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'feature'}\n")
    monkeypatch.chdir(tree)

    config.load_env_file()

    assert config.anthropic_api_key() == "sk-from-the-main-checkout"


def test_the_search_upward_stops_rather_than_leaving_the_project(monkeypatch, tmp_path):
    """No `.env` anywhere above means no key from a file — not somebody else's.

    Walking to the filesystem root would let an unrelated `.env` in a parent
    directory, or in a home directory, supply credentials to this project.
    """
    for name in config.API_KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    project = tmp_path / "project"
    (project / "deep").mkdir(parents=True)
    (tmp_path / ".env").write_text("API_KEY_ANTHROPIC=sk-from-a-stranger\n")
    (project / "pyproject.toml").write_text("[project]\nname='x'\n")
    monkeypatch.chdir(project / "deep")

    config.load_env_file()

    assert config.anthropic_api_key() is None


# ---------------------------------------------------------------- the factory


def test_the_backend_defaults_to_anthropic(monkeypatch):
    monkeypatch.delenv("OPIC_LLM", raising=False)
    assert config.backend() == "anthropic"


def test_an_unknown_backend_names_what_is_allowed(monkeypatch):
    monkeypatch.setenv("OPIC_LLM", "gpt")
    with pytest.raises(ValueError, match="anthropic"):
        config.backend()


def test_ollama_is_still_reachable_by_config(monkeypatch):
    monkeypatch.setenv("OPIC_LLM", "ollama")
    assert isinstance(make_llm_client(), OllamaClient)


def test_the_factory_builds_the_anthropic_client(monkeypatch):
    monkeypatch.setenv("OPIC_LLM", "anthropic")
    monkeypatch.setenv("API_KEY_ANTHROPIC", "sk-test-not-a-real-key")
    assert isinstance(make_llm_client(), AnthropicClient)


def test_no_credentials_is_refused_before_the_exam_starts(monkeypatch):
    """The SDK itself waits until the first request, which is mid-exam.

    By then the candidate has already spoken, so a key that was never set has
    to be caught while the client is being built.
    """
    monkeypatch.setenv("OPIC_LLM", "anthropic")
    for name in (*config.API_KEY_NAMES, "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "load_env_file", lambda path=None: None)

    class Uncredentialed:
        api_key = None
        auth_token = None
        credentials = None

        def __init__(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr("anthropic.Anthropic", Uncredentialed)
    with pytest.raises(MissingCredentials) as caught:
        make_llm_client()
    message = str(caught.value)
    assert "API_KEY_ANTHROPIC" in message
    assert "OPIC_LLM=ollama" in message


def test_an_ant_login_profile_counts_as_credentials(monkeypatch):
    """No key in the environment is not the same as no credentials."""
    monkeypatch.setenv("OPIC_LLM", "anthropic")
    for name in config.API_KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "load_env_file", lambda path=None: None)

    class Profiled:
        api_key = None
        auth_token = None
        credentials = object()

        def __init__(self, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr("anthropic.Anthropic", Profiled)
    assert isinstance(make_llm_client(), AnthropicClient)


# ---------------------------------------------------------------- fixtures


def _a_rated_answer():
    from opic.core.metrics import AnswerMetrics
    from opic.core.questions import Question
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
        words=tuple(
            Word(w, i * 0.4, i * 0.4 + 0.3, 0.9) for i, w in enumerate(SAID.split())
        ),
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
    return question, transcript, metrics


def _a_blueprint() -> tuple[QuestionSlot, ...]:
    return (
        QuestionSlot(
            index=0,
            qtype=QuestionType.SELF_INTRO,
            topic_id=None,
            combo_id=0,
            advanced=False,
            target=ActflLevel.IM2,
        ),
        QuestionSlot(
            index=1,
            qtype=QuestionType.EXPERIENCE,
            topic_id="movies",
            combo_id=0,
            advanced=False,
            target=ActflLevel.IM2,
        ),
    )


# ------------------------------------------------------------ the report's prose


def _narrative_fixtures():
    """A real report, and payloads shaped for it."""
    from adapters.test_narrative import QUOTE, CORRECTION, REPORT, an_analysis

    rewrites = {
        "rewrites": [
            {
                "answer_index": answer.index,
                "text_en": f"A longer answer for {answer.index}.",
                "why_ko": "이유",
                "invented": False,
            }
            for answer in REPORT.answers
        ]
    }
    return REPORT, an_analysis(), rewrites, QUOTE, CORRECTION


def test_write_narrative_makes_two_requests_and_returns_both_halves():
    report, analysis, rewrites, _, _ = _narrative_fixtures()
    client, fake = a_client(json.dumps(analysis), json.dumps(rewrites))

    narrative = client.write_narrative(report)

    assert len(fake.messages.calls) == 2
    assert narrative.analysis is not None
    assert len(narrative.rewrites) == len(report.answers)
    # two different schemas, one per call — not the same request twice
    schemas = [
        call["output_config"]["format"]["schema"] for call in fake.messages.calls
    ]
    assert schemas[0] != schemas[1]
    assert all(
        node.get("additionalProperties") is False
        for schema in schemas
        for node in _objects(schema)
    )


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from _objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _objects(item)


def test_a_failed_analysis_still_returns_the_rewrites():
    """The two halves are independent, and the page renders whichever survived."""
    report, _, rewrites, _, _ = _narrative_fixtures()
    # both analysis attempts come back unusable; both rewrite attempts are fine
    client, _fake = a_client(
        "{}", "{}", json.dumps(rewrites), json.dumps(rewrites)
    )

    narrative = client.write_narrative(report)

    assert narrative.analysis is None
    assert len(narrative.rewrites) == len(report.answers)


def test_a_failed_rewrite_set_still_returns_the_analysis():
    report, analysis, _, _, _ = _narrative_fixtures()
    client, _fake = a_client(json.dumps(analysis), "{}", "{}")

    narrative = client.write_narrative(report)

    assert narrative.analysis is not None
    assert narrative.rewrites == ()


def test_when_both_halves_fail_the_caller_is_told():
    from opic.adapters.narrative import NarrativeError

    report, _, _, _, _ = _narrative_fixtures()
    client, _fake = a_client("{}", "{}", "{}", "{}")

    with pytest.raises(NarrativeError):
        client.write_narrative(report)


def test_the_adapter_satisfies_the_narrative_port():
    from opic.core.ports import NarrativeWriter

    client, _ = a_client()

    assert isinstance(client, NarrativeWriter)


def test_strict_drops_the_keywords_the_api_rejects():
    """Measured, not guessed: `maxItems` came back as a 400 from a real request.

    The bounds are not lost — `parse_analysis` and `parse_rewrites` enforce
    them on the way back in, for both backends.
    """
    from opic.adapters.anthropic_llm import UNSUPPORTED_KEYWORDS
    from opic.adapters.narrative import ANALYSIS_SCHEMA

    sent = strict(ANALYSIS_SCHEMA)

    def keywords(node):
        if isinstance(node, dict):
            yield from node.keys()
            for value in node.values():
                yield from keywords(value)
        elif isinstance(node, list):
            for item in node:
                yield from keywords(item)

    assert not (set(keywords(sent)) & UNSUPPORTED_KEYWORDS)
    # the shared schema is untouched, so the local backend still sees its bounds
    assert "maxItems" in str(ANALYSIS_SCHEMA)
