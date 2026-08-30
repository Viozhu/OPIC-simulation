"""Play the same real question in several voices and speeds, to pick by ear.

A development tool, not part of the simulator. It never runs during an exam and
nothing here is imported by `src/opic`.

Why it exists: candidates reported the question voice as flat and robotic.
There is no metric for that. `SAY_RATE` was chosen by listening to four
candidates, and voice and cadence have to be chosen the same way — this plays
them back to back on the same wording so the comparison is fair, and prints
each duration so the speed difference is a number and not an impression.

    uv run python tools/voice_preview.py --voices Samantha Ava Zoe
    uv run python tools/voice_preview.py --rates 95 115 --pauses 400 700 --clauses 0 200
    uv run python tools/voice_preview.py --session data/sessions/<id>

`--session` speaks the questions a real exam actually asked, which is the only
wording that matters; without it a stock two-sentence prompt is used.

Only the voices installed on this machine can be heard. `say -v '?'` lists
them; the neural ones (Ava, Zoe, Evan, Allison) are a free download under
System Settings, Accessibility, Spoken Content, System Voice, Manage Voices,
and are not present until you fetch them.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import tempfile

from opic.adapters import config
from opic.adapters.tts import with_prosody
from opic.session import store

STOCK = (
    "You said in the survey that you like going to cafes. "
    "Tell me about the last time you went to one, and who you were with."
)


def installed_voices() -> set[str]:
    listing = subprocess.run(
        ["say", "-v", "?"], check=True, capture_output=True, text=True
    ).stdout
    return {line.split("  ")[0].strip() for line in listing.splitlines() if line.strip()}


def questions_from(session: pathlib.Path) -> list[str]:
    state = json.loads((session / store.SESSION_FILE).read_text())
    return [q["text_en"] for q in state.get("questions", [])]


def speak(
    text: str, voice: str, rate: int, pause: int, clause: int, out: pathlib.Path
) -> float:
    spoken = with_prosody(text, config.TTS_LEAD_IN_MS, pause, clause)
    subprocess.run(
        ["say", "-v", voice, "-r", str(rate), "-o", str(out), spoken],
        check=True,
        capture_output=True,
    )
    probe = subprocess.run(
        ["afinfo", str(out)], check=True, capture_output=True, text=True
    ).stdout
    seconds = 0.0
    for line in probe.splitlines():
        if "estimated duration" in line:
            seconds = float(line.split(":")[1].strip().split()[0])
    subprocess.run(["afplay", str(out)], check=True)
    return seconds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voices", nargs="+", default=[config.SAY_VOICE])
    parser.add_argument("--rates", nargs="+", type=int, default=[config.SAY_RATE])
    parser.add_argument(
        "--pauses", nargs="+", type=int, default=[config.TTS_SENTENCE_PAUSE_MS]
    )
    parser.add_argument(
        "--clauses", nargs="+", type=int, default=[config.TTS_CLAUSE_PAUSE_MS]
    )
    parser.add_argument("--session", type=pathlib.Path)
    parser.add_argument(
        "--questions", type=int, default=1, help="how many, when --session is given"
    )
    args = parser.parse_args()

    available = installed_voices()
    missing = [v for v in args.voices if v not in available]
    if missing:
        # Naming them beats a `say` failure per combination, and the fix is a
        # download the tool cannot perform.
        parser.error(
            f"not installed on this machine: {', '.join(missing)}. "
            "System Settings, Accessibility, Spoken Content, System Voice, "
            "Manage Voices."
        )

    texts = (
        questions_from(args.session)[: args.questions] if args.session else [STOCK]
    )

    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "preview.aiff"
        for text in texts:
            print(f"\n{text}\n")
            for voice in args.voices:
                for rate in args.rates:
                    for pause in args.pauses:
                        for clause in args.clauses:
                            label = (
                                f"{voice} @ {rate} wpm, "
                                f"{pause}ms sentence, {clause}ms clause"
                            )
                            print(f"  {label} ... ", end="", flush=True)
                            seconds = speak(text, voice, rate, pause, clause, out)
                            print(f"{seconds:.1f}s")


if __name__ == "__main__":
    main()
