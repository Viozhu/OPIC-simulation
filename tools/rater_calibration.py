"""Measure how far this simulator's grade sits from a real OPIc grade.

A development tool, not part of the simulator. It never runs during an exam and
nothing here is imported by `src/opic`.

Why it exists: `rater_bench.py` puts two raters beside each other, which shows
whether they *disagree* but not which of them is *right*. Candidates reported
the simulator felt strict, and there was nothing in the repository that could
confirm or deny it, because there was no rating from outside the repository to
compare against. This supplies the missing column.

The ground truth is a real OPIc grade, held by a candidate who also took a
session here. Nothing else works: the objective metrics the rater is shown —
words per minute, pause ratio, mean utterance length — come from audio timings,
so a transcript-only corpus would force this tool to invent them, and inventing
a pause ratio of zero tells the rater the speaker never hesitated. A calibration
run on fabricated fluency evidence measures nothing.

    uv run python tools/rater_calibration.py --labels labels.json
    uv run python tools/rater_calibration.py --labels labels.json --regrade

`labels.json` maps a session id to the grade that session's candidate actually
holds:

    {
      "20260821-140338": "IM2",
      "20260825-190621": "IH"
    }

Without `--regrade` the stored per-answer verdicts are reused and the run is
free — that measures the aggregation. With it, every answer is graded again
through the current prompt, which is what a prompt change has to be measured
by. `--regrade` needs credentials: `API_KEY_ANTHROPIC` or `ANTHROPIC_API_KEY`
(a `.env` in the repo root is read), or a profile from `ant auth login`.

WHAT THE NUMBERS MEAN

ACTFL double-rates every operational OPIc: two certified raters score it
blind, and a third arbitrates when they differ. Their published agreement on
English (N=8017, 2012-2014) is 74% exact, 25% adjacent, 1% two or more bands
apart. That is the ceiling a rater can be held to — not 100%, which two trained
humans do not reach on this scale either.

Exact agreement is reported twice, because our scale is not ACTFL's. OPIc splits
ACTFL's single Intermediate Mid into IM1/IM2/IM3 for the Korean market, so three
of our nine bands cover one of theirs. Agreement counted on our scale is the
stricter number; agreement counted after collapsing IM1/IM2/IM3 back into one IM
is the one comparable to the 74%.

The number that answers the complaint is neither. It is the mean *signed* gap:
negative means this simulator grades below the real exam, and by how many bands.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

from opic.core.rubric import ActflLevel
from opic.core.scoring import aggregate
from opic.session.assessments import _answer_from_json

# ACTFL, "Examination Evaluation of the ACTFL OPIc", AAR/OPIc/ACE/R-2015-001,
# Table 6: inter-rater agreement between two certified human raters, English.
HUMAN_EXACT = 0.74
HUMAN_ADJACENT = 0.25
HUMAN_APART = 0.01

# The three OPIc bands that are one ACTFL band. Collapsing them is what makes
# our agreement comparable to a figure computed on ACTFL's own scale.
INTERMEDIATE_MID = {ActflLevel.IM1, ActflLevel.IM2, ActflLevel.IM3}


def actfl_band(level: ActflLevel) -> str:
    """The level as ACTFL would name it, with OPIc's subdivision undone."""
    return "IM" if level in INTERMEDIATE_MID else level.name


def load_session(root: pathlib.Path, session_id: str):
    """Rebuild one session's assessments and blueprint from what is on disk."""
    folder = root / session_id
    answers = sorted(folder.glob("answer-*.json"))
    if not answers:
        raise FileNotFoundError(f"{folder} holds no answer-NN.json files")
    assessments = [_answer_from_json(json.loads(p.read_text("utf-8"))) for p in answers]
    blueprint = tuple(a.question.slot for a in assessments)
    return blueprint, assessments


def regrade(assessments, rater):
    """Grade every stored answer again through the current prompt."""
    from opic.core.scoring import AnswerAssessment

    fresh = []
    for a in assessments:
        scores = rater.rate(a.question, a.transcript, a.metrics)
        fresh.append(
            AnswerAssessment(
                question=a.question,
                transcript=a.transcript,
                dimension_scores=scores,
                metrics=a.metrics,
            )
        )
    return fresh


def report(rows: list[tuple[str, ActflLevel, ActflLevel]]) -> str:
    """One table, and the three numbers that answer the question."""
    if not rows:
        return "No labelled sessions to compare."

    gaps = [ours.rank - official.rank for _, official, ours in rows]
    exact = sum(1 for g in gaps if g == 0) / len(gaps)
    adjacent = sum(1 for g in gaps if abs(g) == 1) / len(gaps)
    apart = sum(1 for g in gaps if abs(g) >= 2) / len(gaps)
    collapsed = sum(
        1 for _, official, ours in rows if actfl_band(official) == actfl_band(ours)
    ) / len(rows)

    lines = [
        f"{len(rows)} labelled session(s).",
        "",
        f"{'session':<20} {'official':>9} {'simulator':>10} {'gap':>5}",
    ]
    for session_id, official, ours in rows:
        gap = ours.rank - official.rank
        lines.append(
            f"{session_id:<20} {official.name:>9} {ours.name:>10} {gap:>+5d}"
        )

    mean_gap = statistics.mean(gaps)
    direction = (
        "grades BELOW the real exam"
        if mean_gap < 0
        else "grades ABOVE the real exam"
        if mean_gap > 0
        else "sits on the real exam"
    )
    lines += [
        "",
        f"mean signed gap   {mean_gap:+.2f} bands — the simulator {direction}",
        f"median gap        {statistics.median(gaps):+.1f} bands",
        "",
        f"{'':<18}{'this rater':>12}{'two humans':>13}",
        f"{'exact (OPIc scale)':<18}{exact:>11.0%}{'—':>13}",
        f"{'exact (ACTFL scale)':<18}{collapsed:>11.0%}{HUMAN_EXACT:>12.0%}",
        f"{'adjacent (±1)':<18}{adjacent:>11.0%}{HUMAN_ADJACENT:>12.0%}",
        f"{'apart (±2 or more)':<18}{apart:>11.0%}{HUMAN_APART:>12.0%}",
        "",
        "Human figures: ACTFL, Examination Evaluation of the ACTFL OPIc,",
        "AAR/OPIc/ACE/R-2015-001, Table 6 (English, N=8017). Two certified",
        "raters agreeing exactly 74% of the time is the ceiling here, not 100%.",
    ]
    if len(rows) < 10:
        lines += [
            "",
            f"NOTE: {len(rows)} session(s) is too few to read a percentage from.",
            "The signed gap is the only figure worth acting on at this N, and",
            "even it moves a lot. Ten labelled sessions is a floor, not a target.",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--labels",
        required=True,
        type=pathlib.Path,
        help="JSON mapping session id to the candidate's real OPIc grade",
    )
    parser.add_argument(
        "--sessions",
        type=pathlib.Path,
        default=pathlib.Path("data/sessions"),
        help="where the session folders live (default: data/sessions)",
    )
    parser.add_argument(
        "--regrade",
        action="store_true",
        help="grade every answer again through the current prompt (costs money)",
    )
    args = parser.parse_args(argv)

    labels = json.loads(args.labels.read_text("utf-8"))
    if not labels:
        print(f"{args.labels} is empty.", file=sys.stderr)
        return 1

    rater = None
    if args.regrade:
        from opic.adapters import make_llm_client

        rater = make_llm_client()

    rows: list[tuple[str, ActflLevel, ActflLevel]] = []
    for session_id, official_name in sorted(labels.items()):
        try:
            official = ActflLevel[official_name]
        except KeyError:
            print(
                f"{session_id}: {official_name!r} is not an OPIc grade; "
                f"expected one of {[level.name for level in ActflLevel]}",
                file=sys.stderr,
            )
            return 1
        try:
            blueprint, assessments = load_session(args.sessions, session_id)
        except FileNotFoundError as exc:
            print(f"skipping {session_id}: {exc}", file=sys.stderr)
            continue
        if rater is not None:
            assessments = regrade(assessments, rater)
        rows.append((session_id, official, aggregate(blueprint, assessments).final_level))

    print(report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
