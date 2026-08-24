---
name: share-test
description: Use when someone else needs to take the OPIc exam from another machine — "compartir el examen", "share-test", "que lo haga mi familiar", "URL pública", "levanta el túnel", "expose the exam". Serves the exam behind a Cloudflare quick tunnel and reports one link that already carries its own key.
---

# Sharing a live exam over a tunnel

Same app as `init-test`, reachable from another computer, with one link that
works and nothing else to explain to the guest.

## The link carries the authentication, because the app has none

`GET /api/sessions/{id}` returns any session to anyone, with no ownership
check. Every graded answer also spends the host's Anthropic credit. So the
whole app sits behind one secret: `OPIC_SHARE_TOKEN` installs a gate
(`web/app.py`, `_install_share_gate`) that 404s every request without it.

The guest's link is `https://<random>.trycloudflare.com/?k=<token>`. On the
first visit the gate swaps the key for an `HttpOnly` cookie and redirects, so
the token does not stay in the address bar, the history or a `Referer` header.

**This is not authentication.** One secret, one guest, no notion of who owns
which session. What makes it safe enough is that it lives for one exam:
the hostname is fresh on every run and dies with the script.

## Bring it up

Preflight first — **REQUIRED: use the `init-test` skill**, especially the cheap
call that proves the rater answers. A tunnel to a server whose rater is
unreachable just moves the failure to someone else's machine.

Then one command, which generates the token, starts the server, opens the
tunnel, tests the gate from outside and prints the link:

```bash
./tools/share.sh          # or: ./tools/share.sh 8011 for another port
```

It refuses to print anything if the gate does not behave: it fetches the public
URL twice, expecting `404` without the key and `200` with it. A gate that
silently failed to install looks exactly like one that worked, and those two
numbers are the whole difference.

Keep the machine awake for the duration — the command to do it is printed with
the link.

## Why Cloudflare and not ngrok

ngrok's free tier puts an interstitial page in front of the app ("You are about
to visit…"), which is the first thing the guest sees and the thing that makes
the link look untrustworthy. A Cloudflare quick tunnel has no interstitial,
gives real TLS and needs no account. The hostname is still somebody else's
domain; the fix for that is a domain of your own, and it is not free.

HTTPS is not cosmetic here: `static/recorder.js` calls `getUserMedia`, which
browsers refuse outside a secure context. No TLS, no microphone.

## When it refuses

| Symptom | Cause |
|---|---|
| `falta cloudflared` | `brew install cloudflared` |
| `no llegó a publicarse en 180s` | The hostname exists only once Cloudflare publishes it, and that lags registration by half a minute. The script waits by asking `1.1.1.1` directly, because this machine's resolver is a local proxy on `127.0.2.2` that caches an `NXDOMAIN` from a premature question and repeats it for minutes — which looks exactly like a dead tunnel. If this fires, the tunnel usually did connect: read `tunnel.log` in the kept directory before blaming the network |
| `el túnel nunca registró` | This network drops QUIC on UDP/7844, so the script forces `--protocol http2` over TCP/443. If even that fails, the log's precheck table says which leg is down |
| `el puerto N ya está ocupado` | Another server holds it, or a previous run did not clean up. `lsof -nP -iTCP:N -sTCP:LISTEN` |
| `el servidor no respondió` | Read the tail it prints. Usually a missing API key, or `data/sessions/.server.lock` held by another process |
| `la puerta no se comporta como debe` | The token did not reach the app. Do not share anything; check that `OPIC_SHARE_TOKEN` is set in the server's environment |
| The guest sees a 404 | They dropped the `?k=…` when copying the link, or twelve hours passed and the cookie expired. Resend the full link |

## Teardown

Ctrl-C. It kills the tunnel and the server, and the link stops existing —
there is no stale URL left pointing at this machine.

## What the host machine carries

Whisper, `say` and the paid API calls all run here, so the guest's exam spends
the host's credit (~$0.09 for fifteen answers) and occupies the single grading
queue. One guest at a time.
