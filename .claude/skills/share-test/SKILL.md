---
name: share-test
description: Use when someone else needs to take the OPIc exam from another machine — "compartir el examen", "share-test", "que lo haga mi familiar", "URL pública", "levanta ngrok", "expose the exam". Brings up the server behind an authenticated ngrok tunnel and reports the URL, user and password.
---

# Sharing a live exam over ngrok

Same app as `init-test`, reachable from another computer. The tunnel is what
makes it work *and* what makes it safe — read the next paragraph before running
anything.

## The tunnel carries the authentication, because the app has none

`GET /api/sessions/{id}` returns any session to anyone, with no ownership
check, and session ids are timestamps — `20260821-090346`. Walking that id
space takes seconds, and it yields the candidate's background survey, the
transcripts of everything they said, and their grades. Every graded answer also
spends the host's Anthropic credit.

So: **never start a tunnel without the basic-auth policy**, and never treat the
password as a formality. Kill the tunnel when the exam ends.

## Bring it up

Preflight first — **REQUIRED: use the `init-test` skill** for it, especially
the cheap call that proves the rater answers. A tunnel to a server whose rater
is unreachable just moves the failure to someone else's machine.

Generate a fresh password every time and keep the policy file out of the repo,
where a password would be committed:

```bash
SP=/tmp/opic-share            # or the session scratchpad
mkdir -p "$SP"
PASS=$(python3 -c "import secrets,string; a=string.ascii_letters+string.digits; print(''.join(secrets.choice(a) for _ in range(16)))")
cat > "$SP/ngrok-policy.yml" <<YAML
on_http_request:
  - actions:
      - type: basic-auth
        config:
          realm: OPIc
          credentials:
            - "familia:${PASS}"
YAML
chmod 600 "$SP/ngrok-policy.yml"
```

`--basic-auth` does not exist in ngrok v3; a traffic policy file is the only
way. Then start both, waiting on conditions rather than sleeping:

```bash
uv run python -m opic.cli --serve                       # background
until curl -sf -o /dev/null http://127.0.0.1:8000/; do sleep 1; done
ngrok http 8000 --traffic-policy-file "$SP/ngrok-policy.yml" \
      --log stdout --log-format logfmt                  # background
```

Read the URL from the agent's own API, not from the log:

```bash
curl -s http://127.0.0.1:4040/api/tunnels \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])"
```

## Prove the auth bites before handing the URL to anyone

A tunnel whose policy silently failed to load looks exactly like one that
worked. Two requests settle it — do not skip this and do not infer it from the
policy file existing:

```bash
curl -s -o /dev/null -w "sin credenciales -> %{http_code}\n" "$URL/"
curl -s -o /dev/null -w "con credenciales  -> %{http_code}\n" -u "familia:$PASS" "$URL/"
```

`401` then `200`. Anything else — especially `200` on the first — means stop
and fix the policy before sharing.

Only then report **URL + usuario + password** together, and tell the guest the
first screen is ngrok's free-tier interstitial ("You are about to visit…") with
a button to continue, not a failure. Also tell them to check the headset's
hardware mute before step 3; see `init-test`.

## When ngrok refuses

| Symptom | Cause |
|---|---|
| `ERR_NGROK_123` … email not verified | Verify at dashboard.ngrok.com/user/settings. The message **names the account** the stored token belongs to — if that is not the account just verified, install a fresh token with `ngrok config add-authtoken`. |
| `ERR_NGROK_123` persists right after verifying | Propagation. Wait a minute and retry before chasing tokens. |
| `version property is required` | Config predates v3. `ngrok config upgrade`. |

## Teardown

Stop ngrok and the server, delete the policy file — it holds a password — and
confirm the port is free. The URL is random and changes on every restart, so a
shared link dies with the tunnel; that is a feature here, not a limitation.

```bash
rm -f "$SP/ngrok-policy.yml"
lsof -nP -iTCP:8000 -sTCP:LISTEN || echo "libre"
```

## What the host machine carries

Whisper, `say` and the paid API calls all run on the host, so the guest's exam
spends the host's credit (~$0.09 for fifteen answers) and occupies the single
grading queue. Keep the machine awake with `caffeinate -i` for the duration.
