# El examen, en pie sin nadie delante

Sustituye a `tools/share.sh` para el caso en que el examen tiene que estar
disponible sin que nadie levante nada. `share.sh` sigue existiendo y sigue
siendo lo correcto para un examen suelto.

## Lo que hace falta

- Un dominio en Cloudflare.
- `brew install cloudflared`.
- El Mac despierto: `sudo pmset -a sleep 0 disablesleep 1`.

## Una vez

```bash
cloudflared tunnel login
cloudflared tunnel create opic          # apunta el UUID que imprime
cloudflared tunnel route dns opic opic.TU-DOMINIO.com
cp tools/deploy/cloudflared-config.yml.template ~/.cloudflared/config.yml
# editar: TUNNEL_ID, USERNAME, HOSTNAME
```

`.env.deploy` en la raíz del repositorio (ignorado por git), con el entorno que
el agente de launchd no hereda de tu terminal:

```bash
API_KEY_ANTHROPIC=sk-ant-...
OPIC_SHARE_TOKEN=<openssl rand -hex 24>
OPIC_PUBLIC_URL=https://opic.TU-DOMINIO.com
OPIC_SHEET_URL=https://script.google.com/macros/s/.../exec
```

Después:

```bash
./tools/deploy/install.sh
```

Imprime el enlace sólo si la puerta contesta 404 sin la clave y 200 con ella.

## La hoja

En una hoja nueva, Extensiones → Apps Script, y este guion:

```javascript
function doPost(e) {
  const row = JSON.parse(e.postData.contents);
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["timestamp", "session_id", "name", "email", "level", "rating", "comment", "report_url"]);
  }
  sheet.appendRow([
    row.timestamp, row.session_id, row.name, row.email,
    row.level, row.rating, row.comment, row.report_url,
  ]);
  return ContentService.createTextOutput("ok");
}
```

Implementar → Nueva implementación → Aplicación web, ejecutar como tú mismo,
con acceso «cualquier usuario». La URL que da es `OPIC_SHEET_URL`.

**Esa URL es el secreto entero:** quien la tenga puede añadir filas. Vive en
`.env.deploy` y en ningún otro sitio.

## Lo que empeora respecto a `share.sh`

`share.sh` es seguro porque vive un examen: el nombre de máquina es nuevo en
cada arranque y muere con el script. Esto borra las dos mitades de esa frase.
Lo que queda es un secreto compartido delante de una aplicación sin noción de
propietario, en pie a todas horas.

Lo que lo compensa, y hay que mantenerlo:

- Los ids de sesión son aleatorios, así que un examen no se encuentra a mano.
- `POST /api/sessions` está limitado por origen.
- Las subidas tienen tope de tamaño.
- Un límite de gasto en la clave de Anthropic. **Ponlo en la consola de
  Anthropic**; no hay nada en este repositorio que pueda imponerlo.
- Rotar `OPIC_SHARE_TOKEN` de vez en cuando: cambiarlo en `.env.deploy` y
  `launchctl kickstart -k gui/$(id -u)/com.opic.server`. Invalida las cookies
  vivas, así que hazlo entre exámenes.

## Cuando falla

| Síntoma | Dónde mirar |
|---|---|
| El enlace da 502 | `data/logs/server.err.log`. Normalmente la clave de la API o `data/sessions/.server.lock` de un proceso anterior |
| El enlace no resuelve | `data/logs/tunnel.err.log`, y `cloudflared tunnel info opic` |
| `/healthz` da 503 | El hilo del worker murió. El servidor contesta pero no transcribe nada. `launchctl kickstart -k gui/$(id -u)/com.opic.server` |
| Todo en pie y nadie puede grabar | Sin HTTPS no hay micrófono. Comprobar que se entra por el nombre de Cloudflare y no por `localhost` desde fuera |
| Las filas no llegan a la hoja | `uv run python -m opic.cli --publish <id>`, que imprime el error real |
