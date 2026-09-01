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

**El enlace de la columna `report_url` sólo abre desde un navegador que ya
tenga la cookie de la puerta** — la que deja una visita anterior a la URL con
`?k=...` en las últimas doce horas. Sin esa cookie da 404, no un error
explicable. Para abrir uno en frío: visitar primero
`https://<tu-dominio>/?k=<OPIC_SHARE_TOKEN>` y luego pulsar el enlace de la
hoja. El token no va en la URL de la hoja a propósito — la hoja se comparte
con mucha más soltura que `.env.deploy`.

Pasada la puerta hay una segunda comprobación, y de ésa el enlace se ocupa
solo: el `?r=...` que lleva es la clave de lectura de esa sesión. La cookie que
identifica al candidato se queda en su navegador, así que sin esa clave el
informe daría 404 también para ti. Abre ese informe y ninguno más, y no sirve
para escribir nada — pero vive en la hoja, así que quien lea la hoja puede leer
ese examen. Rotar `OPIC_SHARE_TOKEN` no la cambia: para cerrar un informe hay
que borrar su fila (y, si de verdad importa, su carpeta en `data/sessions/`).

## Lo que empeora respecto a `share.sh`

`share.sh` es seguro porque vive un examen: el nombre de máquina es nuevo en
cada arranque y muere con el script. Esto borra las dos mitades de esa frase.
Lo que queda es un secreto compartido, el mismo para todos los invitados a la
vez, delante de una aplicación en pie a todas horas.

Lo que lo compensa, y hay que mantenerlo:

- Los ids de sesión son aleatorios, así que un examen no se encuentra a mano.
- Cada sesión tiene dueño: el `POST /api/sessions` deja una cookie propia de
  esa sesión, y sin ella no se lee ni se escribe. La puerta impide que llegue
  un desconocido; esto impide que un invitado lea el examen de otro.
- `POST /api/sessions` está limitado por origen.
- Las subidas tienen tope de tamaño.
- Un límite de gasto en la clave de Anthropic. **Ponlo en la consola de
  Anthropic**; no hay nada en este repositorio que pueda imponerlo.
- Rotar `OPIC_SHARE_TOKEN` de vez en cuando: cambiarlo en `.env.deploy` y
  `launchctl kickstart -k gui/$(id -u)/com.opic.server`. Invalida las cookies
  vivas, así que hazlo entre exámenes.

## Se apaga solo

Veinte minutos después del último examen terminado, y sólo si no queda ninguna
sesión viva, el servidor sale por su propio pie (`opic/web/shutdown.py`). Por
eso `KeepAlive` en `com.opic.server.plist` es `SuccessfulExit: false` y no
`true`: launchd revive un fallo, no una salida deliberada — con `true` el
apagado automático no existiría precisamente en la máquina donde está pensado.

Y por eso el comando del plist termina traduciendo el 143 en 0. El apagado es
un SIGTERM que el proceso se manda a sí mismo, y uvicorn, después de cerrar en
orden, vuelve a lanzarse la señal para conservar su semántica: el proceso
siempre muere de SIGTERM y sale 143, sea deliberado o no. Sin esa traducción,
launchd lee un fallo y lo levanta de vuelta.

El túnel sigue en pie y el enlace da 502 hasta que lo levantes:

```bash
launchctl kickstart -k gui/$(id -u)/com.opic.server
```

Si prefieres dejarlo encendido siempre, el apagado se desactiva pasando
`shutdown_after=None` a `create_app` en `web/serve.py`.

## Cuando falla

| Síntoma | Dónde mirar |
|---|---|
| El enlace da 502 | `data/logs/server.err.log`. Normalmente la clave de la API o `data/sessions/.server.lock` de un proceso anterior. Si el log termina en un apagado limpio, no falló nada: se apagó solo (ver abajo) y hay que levantarlo |
| El servidor no arranca, `data/logs/server.err.log` dice que falta la puerta | `OPIC_SHARE_TOKEN` no está en `.env.deploy` (o no se cargó). Es deliberado: el servidor se niega a arrancar sin la puerta antes que quedar público en silencio |
| El enlace no resuelve | `data/logs/tunnel.err.log`, y `cloudflared tunnel info opic` |
| `/healthz` da 503 | El hilo del worker murió. El servidor contesta pero no transcribe nada. `launchctl kickstart -k gui/$(id -u)/com.opic.server` |
| Todo en pie y nadie puede grabar | Sin HTTPS no hay micrófono. Comprobar que se entra por el nombre de Cloudflare y no por `localhost` desde fuera |
| Las filas no llegan a la hoja | `uv run python -m opic.cli --publish <id>`, que imprime el error real |
