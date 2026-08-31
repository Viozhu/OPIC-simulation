from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import anthropic

from opic.adapters import config, make_llm_client
from opic.adapters.stt import WhisperSpeechToText
from opic.adapters.tts import SayTextToSpeech
from opic.core.scoring import ExamResult
from opic.core.survey import (
    Housing,
    Occupation,
    RecentCourse,
    SurveyAnswers,
    validate_survey,
)
from opic.session import assessments, pages, store
from opic.session.state import AnswerRecord, AnswerState, SessionState
from opic.session.worker import Task, Worker
from opic.web.serve import LockedError, claim_the_lock

ANSWER_SECONDS = 90


def record_answer(
    path: Path,
    seconds: int = ANSWER_SECONDS,
    device: str = ":0",
) -> Path:
    """Capture one spoken answer from the microphone via ffmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "avfoundation", "-i", device,
            "-t", str(seconds),
            "-ar", "16000", "-ac", "1",
            str(path),
        ],
        check=True,
    )
    return path


def play(path: Path) -> None:
    subprocess.run(["afplay", str(path)], check=True)


def run_exam(
    answers: SurveyAnswers,
    self_assess_level: int,
    seed: int,
    session_dir: Path,
    tts,
    stt,
    writer,
    rater,
    recorder: Callable[[Path, int, str], Path] = record_answer,
    player: Callable[[Path], None] = play,
    device: str = ":0",
) -> ExamResult:
    """Run a whole exam over the same session machinery the web interface uses.

    `session_dir` keeps meaning what it meant: this session's folder. It is
    split into the sessions root and the session id so `store` and `Worker` —
    which think in those terms — can be handed the exact layout the CLI already
    wrote.

    Two guards protect a directory that already holds a finished (or
    in-progress) exam: this refuses to run at all if `session_dir` already has
    a `session.json` — reusing one silently overwrote it while leaving the
    previous run's `answer-NN.json` files behind, which used to make a second,
    broken exam report the FIRST exam's grade — and it takes the same
    single-process lock the web server holds over `root`, so a CLI exam can
    never run concurrently with a server evaluating over the same sessions
    folder.
    """
    issues = validate_survey(answers)
    if issues:
        detail = ", ".join(f"{i.error.value}({i.detail})" for i in issues)
        raise ValueError(f"invalid survey: {detail}")

    root = session_dir.parent
    session_id = session_dir.name

    existing = session_dir / store.SESSION_FILE
    if existing.exists():
        raise ValueError(
            f"{session_dir} already holds a session ({existing}); "
            "pass a different --session, or its previous answers and result "
            "will be mixed up with this run's"
        )

    claim_the_lock(root)

    worker = Worker(root=root, tts=tts, stt=stt, writer=writer, rater=rater)

    session_dir.mkdir(parents=True, exist_ok=True)
    state = (
        SessionState.new(session_id, seed, created_at=datetime.now())
        .with_survey(answers)
        .with_level(self_assess_level)
    )
    store.save(root, state)

    worker.submit(Task("generate", session_id))
    worker.drain()

    state = store.load(root, session_id)
    print(f"\n총 {len(state.questions)}개의 질문이 있습니다.\n")

    for question in state.questions:
        print(f"질문 {question.index + 1} / {len(state.questions)}")
        player(Path(question.audio_path))
        recording = store.answer_audio_path(root, session_id, question.index, ".wav")
        recorder(recording, ANSWER_SECONDS, device)
        worker.update(
            session_id,
            lambda s, i=question.index, name=recording.name: s.with_answer(
                AnswerRecord(i, AnswerState.RECORDED, name)
            ),
        )
        worker.submit(Task("evaluate", session_id, question.index))
        print(f"  녹음 완료: {ANSWER_SECONDS}초")

    print("\n채점 중입니다. 15개 답변에 약 1시간이 걸립니다.\n")
    worker.drain()

    state = store.load(root, session_id)
    judged = assessments.read_all_answers(root, session_id, state)
    if not judged:
        raise RuntimeError("no answer could be scored; is Ollama running?")
    print(f"  채점 {len(judged)} / {len(state.questions)}")
    return assessments.aggregate_available(state.questions, judged)


REQUIRED_SURVEY_FIELDS = ("occupation", "is_student", "housing", "selected_item_ids")


def load_survey(path: Path) -> SurveyAnswers:
    """Read survey answers from JSON, failing with something a person can act on.

    Everything here happens before `run_exam` gets a chance to validate, so a
    bare KeyError from this point would be the last thing the user ever sees.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc

    missing = [field for field in REQUIRED_SURVEY_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"{path} is missing: {', '.join(missing)}")

    def choose(enum, value, field):
        try:
            return enum(value)
        except ValueError as exc:
            allowed = ", ".join(member.value for member in enum)
            raise ValueError(
                f"{field} is {value!r}; expected one of: {allowed}"
            ) from exc

    ids = raw["selected_item_ids"]
    if not isinstance(ids, list):
        raise ValueError("selected_item_ids must be a list of item ids")

    course = raw.get("recent_course")
    return SurveyAnswers(
        occupation=choose(Occupation, raw["occupation"], "occupation"),
        is_student=bool(raw["is_student"]),
        housing=choose(Housing, raw["housing"], "housing"),
        selected_item_ids=tuple(ids),
        recent_course=choose(RecentCourse, course, "recent_course") if course else None,
    )


def regenerate_report(session_dir: Path, use_llm: bool = True, force: bool = False) -> int:
    """Rebuild the standalone page for a session that is already graded.

    Separate from running an exam because it is useful on its own: every
    session graded before this command existed still has its `result.json`,
    and the page is a second reading of that file. `--no-llm` renders only the
    derived sections, which needs no key, no network and no cost.
    """
    root, session_id = session_dir.parent, session_dir.name
    target = store.page_path(root, session_id)
    if target.exists() and not force:
        print(f"error: {target} already exists; pass --force to overwrite")
        return 1
    try:
        built = pages.build(root, session_id)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}")
        return 1
    if built is None:
        print(f"error: {session_dir} has no result.json to report on")
        return 1
    report, meta = built

    narrative = None
    if use_llm:
        try:
            client = make_llm_client()
        except (RuntimeError, ValueError) as exc:
            print(f"error: {exc}")
            return 1
        if not hasattr(client, "write_narrative"):
            print("note: this backend writes no prose; rendering the derived page")
        else:
            print("writing the report's analysis and the AL rewrites…")
            try:
                narrative = client.write_narrative(report)
            except Exception as exc:  # noqa: BLE001 - a derived page still beats none
                print(f"note: the narrative failed ({exc}); rendering without it")

    written = pages.write(root, session_id, report, meta, narrative)
    print(f"리포트: {written}")
    return 0


def find_sessions(root: Path, needle: str, out=print) -> int:
    """Listar los exámenes cuyo nombre o correo contienen `needle`.

    Vive en la consola y no en la API a propósito: todos los invitados
    comparten el mismo token de la puerta, así que un endpoint de listado le
    enseñaría a cualquiera de ellos los exámenes de todos los demás.
    """
    wanted = needle.strip().lower()
    if not root.exists():
        out(f"no hay sesiones en {root}")
        return 0

    rows = []
    for directory in sorted(root.iterdir()):
        if not (directory / store.SESSION_FILE).exists():
            continue
        try:
            state = store.load(root, directory.name)
        except (OSError, ValueError, KeyError):
            continue
        if state.candidate is None:
            continue
        haystack = f"{state.candidate.name} {state.candidate.email}".lower()
        if wanted not in haystack:
            continue
        level = ""
        result = store.result_path(root, state.id)
        if result.exists():
            try:
                level = json.loads(result.read_text(encoding="utf-8")).get("final_level", "")
            except (OSError, ValueError, AttributeError):
                level = "?"
        rows.append((state.created_at, state.id, state.candidate, state.step.value, level))

    for created_at, session_id, candidate, step, level in sorted(rows):
        out(
            f"{created_at:%Y-%m-%d %H:%M}  {session_id}  "
            f"{candidate.name} <{candidate.email}>  {step}  {level}"
        )
    out(f"{len(rows)} sesión(es)")
    return 0


def publish_session(
    root: Path,
    session_id: str,
    sink=None,
    public_url: str | None = None,
    out=print,
) -> int:
    """Mandar a la hoja la fila de un examen, otra vez si hace falta.

    Sirve para un examen anterior a que esto existiera y para uno cuyo envío
    agotó los reintentos del worker. Reenvía aunque ya conste publicado: si la
    fila se perdió del otro lado, nada de este lado puede enterarse.
    """
    from opic.adapters.sheets import make_sheet_sink
    from opic.session.publish import sheet_row

    sink = sink if sink is not None else make_sheet_sink()
    base = public_url if public_url is not None else os.environ.get("OPIC_PUBLIC_URL", "").strip()

    try:
        state = store.load(root, session_id)
    except (FileNotFoundError, OSError, ValueError, KeyError) as error:
        out(f"error: {error}")
        return 1
    if state.feedback is None:
        out(f"{session_id}: sin feedback que publicar")
        return 1

    result = None
    path = store.result_path(root, session_id)
    if path.exists():
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = None

    try:
        sink.append(sheet_row(state, result, base))
    except Exception as error:  # noqa: BLE001 - lo que falle, se informa igual
        out(f"error: la hoja no aceptó la fila: {error}")
        return 1

    store.save(root, state.with_feedback(replace(state.feedback, published=True)))
    out(f"{session_id}: publicado")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opic", description="Run a local OPIc mock exam")
    parser.add_argument("--survey", type=Path, help="survey answers as JSON")
    parser.add_argument("--level", type=int, choices=range(1, 7))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--session", type=Path, default=Path("data/sessions/latest"))
    parser.add_argument(
        "--device",
        default=":0",
        help="avfoundation input, e.g. ':2'. List them with: "
        "ffmpeg -f avfoundation -list_devices true -i ''",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="run the web interface instead of the command-line exam",
    )
    parser.add_argument(
        "--report",
        type=Path,
        metavar="SESSION_DIR",
        help="rebuild report-ko.html for an already-graded session and exit",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="with --report, render only the sections derived from result.json",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="with --report, overwrite an existing report-ko.html",
    )
    parser.add_argument(
        "--find",
        metavar="TEXT",
        help="list sessions whose candidate name or email contains TEXT, and exit",
    )
    parser.add_argument(
        "--publish",
        metavar="SESSION_ID",
        help="send this session's row to the sheet again, and exit",
    )
    parser.add_argument(
        "--sessions-root",
        type=Path,
        default=Path("data/sessions"),
        help="where sessions live; used by --find and --publish",
    )
    args = parser.parse_args(argv)

    if args.find is not None:
        return find_sessions(args.sessions_root, args.find)

    if args.publish is not None:
        return publish_session(args.sessions_root, args.publish)

    if args.report is not None:
        return regenerate_report(args.report, use_llm=not args.no_llm, force=args.force)

    if args.serve:
        import uvicorn

        from opic.web.serve import app

        uvicorn.run(app(), host="127.0.0.1", port=8000)
        return 0

    if args.survey is None or args.level is None:
        print("error: --survey and --level are required unless --serve is given")
        return 1

    try:
        answers = load_survey(args.survey)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    try:
        client = make_llm_client()
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    try:
        result = run_exam(
            answers=answers,
            self_assess_level=args.level,
            seed=args.seed,
            session_dir=args.session,
            tts=SayTextToSpeech(cache_dir=Path("data/tts_cache")),
            stt=WhisperSpeechToText(),
            writer=client,
            rater=client,
            device=args.device,
        )
    except urllib.error.URLError as exc:
        print(f"error: cannot reach Ollama at {config.OLLAMA_URL} ({exc.reason}).")
        print(f"       start it with `ollama serve` and pull {config.OLLAMA_MODEL}.")
        return 1
    except anthropic.APIError as exc:
        # Not a RuntimeError, so without this the candidate's finished exam ends
        # in a traceback. The two that actually happen — an exhausted credit
        # balance and a revoked key — both arrive this way, and neither is worth
        # retrying.
        print(f"error: the Anthropic API refused the request: {exc}")
        print(f"       per-answer results, if any, are under {args.session}")
        return 1
    except LockedError as exc:
        print(f"error: {exc}")
        return 1
    except RuntimeError as exc:
        print(f"error: {exc}")
        print(f"       this usually means the rater stopped answering partway through;")
        print(f"       per-answer results, if any, are under {args.session}")
        return 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        print(f"       per-answer results, if any, are under {args.session}")
        return 1
    from opic.core.report import build_report, render_text

    state = store.load(args.session.parent, args.session.name)
    questions = [assessments.question_from_record(r) for r in state.questions]
    print()
    print(render_text(build_report(result, questions)))
    print(f"\n결과 파일: {args.session / 'result.json'}")
    page = pages.write_with_narrator(
        args.session.parent,
        args.session.name,
        client if hasattr(client, "write_narrative") else None,
    )
    if page is not None:
        print(f"리포트: {page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
