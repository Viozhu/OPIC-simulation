#!/usr/bin/env bash
#
# Serve the exam from this machine and hand one person a link to it.
#
# The link carries a secret in `?k=`; the app 404s without it, and swaps it for
# a cookie on the first visit so the token does not stay in the address bar.
# The tunnel is a Cloudflare quick tunnel: a fresh random hostname each run,
# real TLS, no account, and no interstitial page in front of the app.
#
# Nothing here is authentication. One secret, one guest, and the app still has
# no notion of who owns a session — so the tunnel lives for the length of one
# exam and dies with this script.
#
# Usage:  tools/share.sh [port]

set -euo pipefail

PORT="${1:-8000}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$(mktemp -d "${TMPDIR:-/tmp}/opic-share.XXXXXX")"
SERVER_PID=""
TUNNEL_PID=""

KEEP_LOGS=0

cleanup() {
  echo
  echo "==> cerrando"
  [[ -n "$TUNNEL_PID" ]] && kill "$TUNNEL_PID" 2>/dev/null || true
  [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true
  if [[ "$KEEP_LOGS" == "1" ]]; then
    echo "    logs en $RUN"
  else
    rm -rf "$RUN"
  fi
  echo "    el enlace ya no existe"
}
trap cleanup EXIT INT TERM

command -v cloudflared >/dev/null || {
  echo "falta cloudflared: brew install cloudflared" >&2
  exit 1
}

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "el puerto $PORT ya está ocupado; cierra el otro servidor primero" >&2
  exit 1
fi

TOKEN="$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")"

echo "==> arrancando el servidor en :$PORT"
cd "$ROOT"
OPIC_SHARE_TOKEN="$TOKEN" uv run uvicorn --factory opic.web.serve:app \
  --host 127.0.0.1 --port "$PORT" >"$RUN/server.log" 2>&1 &
SERVER_PID=$!

# El servidor carga el modelo y reanuda sesiones, así que puede tardar. Se
# espera a que responda, no a un número de segundos inventado.
for _ in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/?k=$TOKEN" || true)"
  [[ "$code" == "303" || "$code" == "200" ]] && break
  kill -0 "$SERVER_PID" 2>/dev/null || { echo "el servidor murió:"; tail -20 "$RUN/server.log"; exit 1; }
  sleep 1
done
[[ "$code" == "303" || "$code" == "200" ]] || { echo "el servidor no respondió:"; tail -20 "$RUN/server.log"; exit 1; }

echo "==> abriendo el túnel"
# `--protocol http2` y no el automático. Por defecto cloudflared intenta QUIC,
# que es UDP al puerto 7844, y hay redes domésticas y corporativas que lo tiran:
# el túnel entonces reintenta contra un borde tras otro sin llegar a servir
# nada, con la URL ya impresa y engañosamente lista. http2 va por TCP/443, que
# sale de cualquier sitio. Se pierde algo de latencia y no importa aquí.
#
# `--edge-ip-version 4` por lo mismo: el primer borde que elige suele ser IPv6
# y aquí agota el tiempo antes de reintentar por IPv4, unos segundos tirados.
cloudflared tunnel --no-autoupdate --protocol "${OPIC_TUNNEL_PROTOCOL:-http2}" \
  --edge-ip-version "${OPIC_TUNNEL_IP_VERSION:-4}" \
  --url "http://127.0.0.1:$PORT" >"$RUN/tunnel.log" 2>&1 &
TUNNEL_PID=$!

URL=""
for _ in $(seq 1 60); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$RUN/tunnel.log" | head -1 || true)"
  [[ -n "$URL" ]] && break
  kill -0 "$TUNNEL_PID" 2>/dev/null || { echo "el túnel murió:"; tail -20 "$RUN/tunnel.log"; exit 1; }
  sleep 1
done
[[ -n "$URL" ]] || { echo "el túnel no dio URL:"; tail -20 "$RUN/tunnel.log"; exit 1; }

# cloudflared imprime la URL en cuanto la reserva, antes de tener conexión con
# el borde. En ese hueco el hostname todavía no existe en DNS y curl devuelve
# 000: no es que la puerta esté abierta o cerrada, es que no hay puerta que
# probar. Lo que marca el momento es esta línea del log, no un cronómetro.
echo "==> esperando a que el túnel registre"
HOST="${URL#https://}"
registered=0
for _ in $(seq 1 90); do
  if grep -q "Registered tunnel connection" "$RUN/tunnel.log"; then registered=1; break; fi
  kill -0 "$TUNNEL_PID" 2>/dev/null || break
  sleep 1
done
if [[ "$registered" != "1" ]]; then
  echo "el túnel nunca registró conexión con el borde" >&2
  tail -20 "$RUN/tunnel.log" >&2
  KEEP_LOGS=1
  exit 1
fi

# Registrar no es lo mismo que resolver: el nombre tarda todavía medio minuto
# en publicarse, y aquí está la trampa. Preguntar por él antes de que exista
# no devuelve un error pasajero: el resolver de esta máquina (127.0.2.2, un
# proxy local) guarda el NXDOMAIN y lo repite durante minutos, así que la
# primera pregunta prematura envenena todas las siguientes y el enlace parece
# roto cuando el túnel está perfectamente en pie.
#
# Por eso se pregunta a 1.1.1.1, que no pasa por esa caché, y no se toca el
# resolver local hasta que hay respuesta positiva que cachear.
echo "==> esperando a que el nombre se publique"
DEADLINE=$((SECONDS + 180))
resolved=""
while ((SECONDS < DEADLINE)); do
  resolved="$(dig +short A "$HOST" @1.1.1.1 2>/dev/null | head -1)"
  [[ -n "$resolved" ]] && break
  kill -0 "$TUNNEL_PID" 2>/dev/null || break
  sleep 3
done
if [[ -z "$resolved" ]]; then
  echo "$HOST no llegó a publicarse en 180s" >&2
  tail -20 "$RUN/tunnel.log" >&2
  KEEP_LOGS=1
  exit 1
fi
echo "    $HOST -> $resolved"

# La puerta se prueba desde fuera, contra la URL pública, antes de dársela a
# nadie. Una puerta que no cierra tiene exactamente el mismo aspecto que una
# que sí, y la diferencia son estos dos números.
# `--resolve` para no depender tampoco aquí del resolver local, que puede
# seguir arrastrando un negativo de una ejecución anterior. El invitado, con su
# propia caché limpia, resuelve sin más.
echo "==> probando la puerta desde fuera"
PIN=(--resolve "$HOST:443:$resolved")
for _ in $(seq 1 10); do
  sin="$(curl -s "${PIN[@]}" -o /dev/null -m 10 -w '%{http_code}' "$URL/" || true)"
  con="$(curl -sL "${PIN[@]}" -o /dev/null -m 10 -w '%{http_code}' -c "$RUN/jar" "$URL/?k=$TOKEN" || true)"
  [[ "$sin" == "404" && "$con" == "200" ]] && break
  sleep 3
done

echo "    sin la clave -> $sin"
echo "    con la clave -> $con"
if [[ "$sin" != "404" || "$con" != "200" ]]; then
  echo "la puerta no se comporta como debe; no compartas nada" >&2
  tail -20 "$RUN/tunnel.log" >&2
  KEEP_LOGS=1
  exit 1
fi

cat <<FIN

    ────────────────────────────────────────────────────────────
     Enlace para el candidato:

       $URL/?k=$TOKEN

     Se abre en cualquier navegador. La clave desaparece de la
     barra de direcciones al entrar; si recarga, sigue dentro.
    ────────────────────────────────────────────────────────────

    Esta máquina hace el trabajo: Whisper, \`say\` y las llamadas de
    pago. Un examen de quince respuestas gasta ~0,09 $ de tu crédito.
    Mantenla despierta:  caffeinate -i -w $$

    Ctrl-C cierra el túnel y mata el enlace.

FIN

wait "$SERVER_PID"
