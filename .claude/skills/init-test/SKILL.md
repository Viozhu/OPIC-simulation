---
name: init-test
description: Use when starting a live OPIc exam on this machine — "levanta el examen", "init-test", "quiero hacer un examen", "arranca el simulador", "start the exam", or any request to run the simulator against a real microphone rather than the test suite. Covers preflight, launch, handover, and teardown.
---

# Starting a live OPIc exam

Brings the simulator up and hands a human a URL they can speak into. This is
the real app against a real microphone — not `pytest`, and not the bench, which
grades stored answers from disk.

## Preflight — check all five before launching

A failure found here costs a command; the same failure found at question 12
costs the exam.

```bash
which say || echo "FALTA: say (solo macOS)"
lsof -nP -iTCP:8000 -sTCP:LISTEN || echo "puerto 8000 libre"
du -sh ~/.cache/huggingface/hub/models--Systran--faster-whisper-medium 2>/dev/null \
  || echo "Whisper sin cachear: primera corrida descarga ~1.5 GB"
curl -sf -m 2 http://127.0.0.1:11434/api/tags >/dev/null && echo "ollama corriendo" || echo "ollama parado"
echo "OPIC_LLM=${OPIC_LLM:-anthropic (default)}"
```

Then confirm the rater can actually be reached, because the exam does not find
out until the first answer is graded — after the candidate has spoken:

```bash
uv run python -c "from opic.adapters import make_llm_client; print(type(make_llm_client()).__name__)"
```

`AnthropicClient` needs credit on the account, not just a key. A key with a zero
balance authenticates fine and fails at `/v1/messages` with
`Your credit balance is too low`. Verify with one cheap call before handing over
the URL:

```bash
uv run python -c "
from opic.adapters import config; import anthropic
config.load_env_file()
c = anthropic.Anthropic(api_key=config.anthropic_api_key())
r = c.messages.create(model=config.ANTHROPIC_MODEL, max_tokens=8,
                      messages=[{'role':'user','content':'Say OK.'}])
print('rater reachable:', r.content[0].text)"
```

`data/sessions/.server.lock` holding a dead pid is **not** a problem —
`claim_the_lock` takes over a stale lock. A live pid there means a server is
already running; do not start a second one.

## Launch and wait on a condition, never a sleep

```bash
uv run python -m opic.cli --serve          # background
until curl -sf -o /dev/null http://127.0.0.1:8000/; do sleep 1; done
```

Then prove it serves, don't assume:

```bash
curl -s http://127.0.0.1:8000/ | grep -o '<title>[^<]*</title>'   # OPIc 모의고사
```

## Hand over, don't drive

The point is a real microphone, so a browser automation tool defeats the
exercise. Give the human **http://localhost:8000** — `localhost` and
`127.0.0.1` are both secure origins, but say `localhost`, since that is the one
people have already granted permissions to.

Tell them the five steps so they know where they are:
`1 배경 설문 · 2 자기 평가 · 3 마이크 점검 · 4 예시 문항 · 5 시험`.

Then watch the server log for failures while they take it, filtering to the
lines worth acting on rather than tailing everything:

```
Traceback|Error|Exception|FAILED| 5[0-9][0-9] |RaterError|credit|rate_limit|overloaded
```

## Three traps that are live right now

- **Step 3 lets a silent recording through.** `다음` enables as soon as
  recording stops; nothing checks the blob has sound. A muted headset produces
  exactly this and the exam proceeds — fifteen answers of nothing. When someone
  reports hearing no playback, do not guess between "mic captured nothing" and
  "playback is broken": they look identical on screen and are fixed in opposite
  ways. `mic-probe.md` in this directory measures the blob and says which.
- **A permanently failing rater never marks the session failed.** The candidate
  gets a timeout screen and the only evidence is the console. Watch the log.
- **One process only.** Never pass `--workers`; two would be two queues over
  one sessions folder.

## Teardown

Stop the server, then confirm the port is actually free — a process that
ignored the signal looks identical to a clean shutdown until the next launch
fails.

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN || echo "libre"
```

Sessions live under `data/sessions/<id>/`; they survive a restart and the exam
resumes where it left off, so stopping the server is not the same as
abandoning an exam.
