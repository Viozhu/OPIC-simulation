"""The composition point for the two language-model adapters.

Both implement `QuestionWriter` and `Rater`, so everything that runs an exam
takes one object and never learns which one it got.
"""

from __future__ import annotations

from typing import Any

from opic.adapters import config


def make_llm_client(backend: str | None = None) -> Any:
    """The client the exam should use, chosen once, from the environment.

    Reads `.env` first so a key written there reaches a plain
    `uv run python -m opic.cli` with nothing exported. An already-exported
    variable still wins — see `config.load_env_file`.
    """
    config.load_env_file()
    chosen = backend or config.backend()

    if chosen == "ollama":
        from opic.adapters.llm import OllamaClient

        return OllamaClient()

    from opic.adapters.anthropic_llm import AnthropicClient

    # `AnthropicClient` raises `MissingCredentials` here rather than at the
    # first request, so a key that was never set stops the exam before the
    # candidate has spoken. Both the CLI and the server let that surface.
    return AnthropicClient()
