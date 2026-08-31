#!/usr/bin/env bash
# Instala los dos agentes de launchd a partir de las plantillas.
# No crea el túnel ni el registro DNS: eso son dos órdenes de cloudflared que
# piden tu cuenta, y están en docs/deploy.md.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
UV="$(command -v uv || true)"
CLOUDFLARED="$(command -v cloudflared || true)"

[ -n "$UV" ] || { echo "falta uv"; exit 1; }
[ -n "$CLOUDFLARED" ] || { echo "falta cloudflared: brew install cloudflared"; exit 1; }
[ -f "$REPO/.env.deploy" ] || { echo "falta $REPO/.env.deploy — ver docs/deploy.md"; exit 1; }
[ -f "$HOME/.cloudflared/config.yml" ] || { echo "falta ~/.cloudflared/config.yml — ver docs/deploy.md"; exit 1; }

mkdir -p "$REPO/data/logs" "$AGENTS"

for name in com.opic.server com.opic.tunnel; do
  sed -e "s|REPO|$REPO|g" -e "s|UV|$UV|g" -e "s|CLOUDFLARED|$CLOUDFLARED|g" \
    "$REPO/tools/deploy/$name.plist.template" > "$AGENTS/$name.plist"
  launchctl unload "$AGENTS/$name.plist" 2>/dev/null || true
  launchctl load "$AGENTS/$name.plist"
  echo "cargado $name"
done

echo "esperando a que el servidor conteste…"
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
    echo "servidor en pie"
    break
  fi
  sleep 2
done

# Las mismas dos comprobaciones que hace share.sh, por la misma razón: una
# puerta que no se instaló se ve igual que una que funciona, y la diferencia
# son estos dos números.
HOSTNAME_URL="$(grep -m1 'hostname:' "$HOME/.cloudflared/config.yml" | awk '{print $3}')"
TOKEN="$(grep -m1 '^OPIC_SHARE_TOKEN=' "$REPO/.env.deploy" | cut -d= -f2-)"
sin_clave="$(curl -s -o /dev/null -w '%{http_code}' "https://$HOSTNAME_URL/")"
con_clave="$(curl -s -o /dev/null -w '%{http_code}' -L "https://$HOSTNAME_URL/?k=$TOKEN")"
if [ "$sin_clave" != "404" ] || [ "$con_clave" != "200" ]; then
  echo "la puerta no se comporta como debe (sin clave: $sin_clave, con clave: $con_clave)"
  echo "NO compartas el enlace. Revisa OPIC_SHARE_TOKEN en .env.deploy"
  exit 1
fi

echo
echo "enlace para los invitados:"
echo "  https://$HOSTNAME_URL/?k=$TOKEN"
