"""Compare the local rater against Claude on the same real answers.

A development tool, not part of the simulator. It never runs during an exam and
nothing here is imported by `src/opic`.

Why it exists: nothing tells us whether an IH from `qwen3:14b` means anything.
This puts a second opinion beside it on the same transcripts, with the same
schema and the same `parse_rating` filter, so the comparison is between two
raters rather than between two levels of rigour.

The local side is free: every `answer-NN.json` already holds the verdict the
exam produced, so only the Claude side is paid for and re-running the local
model is never necessary.

    uv run python tools/rater_bench.py --session data/sessions/<id>

Needs credentials: `API_KEY_ANTHROPIC` or `ANTHROPIC_API_KEY` (a `.env` in the
repo root is read), or a profile from `ant auth login`.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import pathlib
import re
import time
from dataclasses import dataclass

from opic.adapters import config
from opic.adapters.anthropic_llm import strict
from opic.adapters.llm import RATING_SCHEMA, rating_prompt, parse_rating
from opic.core.rubric import DIMENSION_LABELS_KO, Dimension
from opic.core.scoring import DimensionScore
from opic.session.assessments import _answer_from_json

# Anthropic list prices per million tokens, cached 2026-06-24. Only used to put
# a number on a run that already happened — never to pick a model.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

NO_EFFORT = frozenset({"claude-haiku-4-5", "claude-sonnet-4-5"})

_WORD = re.compile(r"[a-z0-9']+")


# ---------------------------------------------------------------- comparison


@dataclass(frozen=True, slots=True)
class Agreement:
    """How close two ratings of the same answer are, in ACTFL bands."""

    exact: int
    within_one: int
    mean_gap: float


def agreement(
    local: tuple[DimensionScore, ...], remote: tuple[DimensionScore, ...]
) -> Agreement:
    left = {s.dimension: s.level.rank for s in local}
    right = {s.dimension: s.level.rank for s in remote}
    gaps = [abs(left[d] - right[d]) for d in Dimension]
    return Agreement(
        exact=sum(1 for g in gaps if g == 0),
        within_one=sum(1 for g in gaps if g <= 1),
        mean_gap=sum(gaps) / len(gaps),
    )


def rewrite_overlap(quote: str, correction_en: str) -> float:
    """Share of the quote's words that survive into the correction.

    A HINT, not a measurement. A real rewrite keeps most of the quote and
    changes a little; a description of the mistake ("the verb tense is wrong")
    shares almost nothing with it. But a legitimate correction can also rewrite
    a sentence wholesale, so a low score means "worth reading", never "wrong".
    Nothing in this file decides that question — the report shows both texts and
    leaves it to a human, exactly as the phase 2 rater note did.
    """
    said = set(_WORD.findall(quote.lower()))
    fixed = set(_WORD.findall(correction_en.lower()))
    if not said:
        return 0.0
    return len(said & fixed) / len(said)


# ---------------------------------------------------------------- the client


def rate_with_claude(client, model: str, effort: str, assessment):
    """One rating, through the same prompt and the same parser as the local one."""
    prompt = rating_prompt(assessment.question, assessment.transcript, assessment.metrics)
    started = time.monotonic()
    # `effort` is rejected outright by Haiku 4.5 and Sonnet 4.5, so it is sent
    # only to the models that accept it rather than being hardcoded into every
    # request — a cheap reference rater is a legitimate thing to want here.
    output_config = {"format": {"type": "json_schema", "schema": strict(RATING_SCHEMA)}}
    if effort and model not in NO_EFFORT:
        output_config["effort"] = effort
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        output_config=output_config,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.monotonic() - started
    text = next(b.text for b in response.content if b.type == "text")
    payload = json.loads(text)
    scores = parse_rating(payload, assessment.transcript.text)
    return scores, payload, elapsed, response.usage


# ---------------------------------------------------------------- the report


def _dimension_block(score: DimensionScore) -> str:
    rows = [
        f"<p class='level'>{html.escape(DIMENSION_LABELS_KO[score.dimension])}: "
        f"<strong>{score.level.name}</strong></p>",
        f"<p class='comment'>{html.escape(score.comment_ko)}</p>",
    ]
    for item in score.evidence:
        overlap = rewrite_overlap(item.quote, item.correction_en)
        flag = " <span class='hint'>· 겹침 낮음</span>" if overlap < 0.25 else ""
        rows.append(
            "<div class='ev'>"
            f"<p class='quote'>“{html.escape(item.quote)}”</p>"
            f"<p>{html.escape(item.issue_ko)}</p>"
            f"<p class='fix'>→ {html.escape(item.correction_en)} "
            f"<span class='hint'>(겹침 {overlap:.0%}){flag}</span></p>"
            "</div>"
        )
    if not score.evidence:
        rows.append("<p class='hint'>근거 없음</p>")
    return "".join(rows)


def render(rows: list[dict], summary: dict) -> str:
    head = (
        "<title>Rater bench</title><style>"
        "body{font:15px/1.55 -apple-system,system-ui,sans-serif;margin:2rem auto;max-width:1100px;color:#1a1a1f}"
        "table{border-collapse:collapse;margin:1rem 0}td,th{border:1px solid #ddd;padding:.4rem .7rem;text-align:left}"
        ".pair{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:.5rem 0 2rem}"
        ".col{background:#fafafc;border:1px solid #e3e3e8;border-radius:8px;padding:.8rem 1rem}"
        ".col h4{margin:.1rem 0 .6rem}.ev{background:#fff;border:1px solid #e8e8ee;border-radius:6px;padding:.5rem .7rem;margin:.4rem 0}"
        ".quote{font-style:italic}.fix{color:#1d4ed8}.hint{color:#77777f;font-size:.85rem}"
        ".level{margin:.6rem 0 .2rem}.comment{margin:.1rem 0 .4rem}"
        "pre{white-space:pre-wrap;background:#f4f4f8;padding:.7rem;border-radius:6px}"
        "</style>"
    )
    parts = [head, "<h1>Rater bench — 로컬 vs Claude</h1>"]
    parts.append(
        "<p>Both sides went through the same prompt, the same schema and the same "
        "<code>parse_rating</code> filter. 겹침 is a hint for reading, not a score: "
        "it is the share of the quote's words that survive into the correction.</p>"
    )
    parts.append("<table><tr><th>측정</th><th>값</th></tr>")
    for key, value in summary.items():
        parts.append(f"<tr><td>{html.escape(key)}</td><td>{html.escape(str(value))}</td></tr>")
    parts.append("</table>")

    for row in rows:
        parts.append(f"<h3>질문 {row['index'] + 1} — {html.escape(row['question_en'])}</h3>")
        parts.append(f"<pre>{html.escape(row['transcript'])}</pre>")
        parts.append(
            f"<p class='hint'>일치 {row['agreement'].exact}/5 · "
            f"±1 이내 {row['agreement'].within_one}/5 · "
            f"평균 차이 {row['agreement'].mean_gap:.2f} 등급 · "
            f"Claude {row['elapsed']:.0f}s</p>"
        )
        parts.append("<div class='pair'>")
        for title, scores in (("로컬 (qwen3:14b)", row["local"]), ("Claude", row["claude"])):
            parts.append(f"<div class='col'><h4>{title}</h4>")
            parts.extend(_dimension_block(s) for s in scores)
            parts.append("</div>")
        parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------- entry point


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=pathlib.Path, required=True)
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--limit", type=int, default=0, help="0 = every answer")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/bench"))
    args = parser.parse_args()

    try:
        import anthropic
    except ImportError:
        print("error: the `anthropic` package is missing — run `uv sync`.")
        return 1

    config.load_env_file()
    if not config.anthropic_api_key() and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        print("error: no credentials found in the environment or in .env.")
        print("       put API_KEY_ANTHROPIC=... in .env, export ANTHROPIC_API_KEY=...,")
        print("       or run `ant auth login`.")
        print("       note: a key exported in another shell does not reach this one.")
        return 1

    files = sorted(args.session.glob("answer-*.json"))
    if not files:
        print(f"error: no answer-NN.json under {args.session}")
        return 1
    if args.limit:
        files = files[: args.limit]

    key = config.anthropic_api_key()
    client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    rows: list[dict] = []
    tokens_in = tokens_out = 0
    total_seconds = 0.0
    discarded = 0

    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        assessment = _answer_from_json(raw)
        print(f"rating a{assessment.question_index:02d} …", flush=True)
        try:
            scores, payload, elapsed, usage = rate_with_claude(
                client, args.model, args.effort, assessment
            )
        except Exception as error:  # noqa: BLE001 — one failure must not lose the rest
            print(f"  FAILED: {type(error).__name__}: {error}", flush=True)
            continue

        offered = sum(len(entry.get("evidence", ())) for entry in payload.values())
        kept = sum(len(s.evidence) for s in scores)
        discarded += offered - kept
        tokens_in += usage.input_tokens
        tokens_out += usage.output_tokens
        total_seconds += elapsed

        rows.append(
            {
                "index": assessment.question_index,
                "question_en": assessment.question.text_en,
                "transcript": assessment.transcript.text,
                "local": assessment.dimension_scores,
                "claude": scores,
                "agreement": agreement(assessment.dimension_scores, scores),
                "elapsed": elapsed,
            }
        )
        print(
            f"  {elapsed:.0f}s · agreement {rows[-1]['agreement'].exact}/5 · "
            f"{usage.input_tokens} in / {usage.output_tokens} out",
            flush=True,
        )

    if not rows:
        print("error: every rating failed; nothing to report.")
        return 1

    price_in, price_out = PRICES.get(args.model, (0.0, 0.0))
    cost = tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
    summary = {
        "answers compared": len(rows),
        "model": args.model,
        "effort": args.effort,
        "exact level agreement": f"{sum(r['agreement'].exact for r in rows)} / {len(rows) * 5}",
        "within one band": f"{sum(r['agreement'].within_one for r in rows)} / {len(rows) * 5}",
        "mean gap (bands)": f"{sum(r['agreement'].mean_gap for r in rows) / len(rows):.2f}",
        "quotes Claude offered that were not in the transcript": discarded,
        "Claude wall clock": f"{total_seconds:.0f}s total, {total_seconds / len(rows):.0f}s per answer",
        "tokens": f"{tokens_in} in / {tokens_out} out (output includes thinking)",
        "cost at list price": f"${cost:.2f}",
    }

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = args.out / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.html").write_text(render(rows, summary), encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Machine-readable verdicts, so two runs can be compared to each other and
    # not only each to the local rater. Without this the levels exist solely
    # inside the HTML, which makes a model sweep a scraping exercise.
    (out_dir / "verdicts.json").write_text(
        json.dumps(
            {
                "model": args.model,
                "effort": args.effort,
                "session": str(args.session),
                "answers": [
                    {
                        "index": r["index"],
                        "local": {s.dimension.value: s.level.name for s in r["local"]},
                        "claude": {s.dimension.value: s.level.name for s in r["claude"]},
                        "seconds": round(r["elapsed"], 1),
                    }
                    for r in rows
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print(f"\nreport: {out_dir / 'report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
