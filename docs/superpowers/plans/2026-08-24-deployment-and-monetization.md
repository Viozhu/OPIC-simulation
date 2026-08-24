# Deploy — plan técnico

Fecha: 2026-08-24
Alcance: **solo técnico**. Cobro, marca y cumplimiento quedan fuera a propósito.
Restricciones: STT propio (el audio no sale a terceros), caja por debajo de 20€/mes.

## 0. Verificado antes de planificar

Cuatro cosas comprobadas, no supuestas. Dos cambiaron el plan.

### ARM sirve: no hay que compilar nada ✅
`ctranslate2 4.8.1` y `onnxruntime 1.29.0` publican rueda
`manylinux_2_28_aarch64` para cp313, y ya están en el `uv.lock` de este
proyecto (líneas 122 y 436). El contenedor ARM instala igual que el Mac.

### Piper funciona, y la nota de `config.py:6` diagnostica mal la causa ⚠️
`config.py:6` y `docs/.../phase-2-adapters-design.md` §6 bis dicen que
`piper-tts` trae la ruta de datos de la máquina de compilación incrustada y que
no hay forma limpia de rodearlo. La primera mitad es cierta; la conclusión no.

Lo que pasa de verdad, medido con `piper-tts 1.7.0` en este Mac: espeak-ng
guarda la ruta de datos en un buffer de **160 caracteres**. Si la ruta que se le
pasa llega o supera ese tamaño, la trunca, cae a la ruta compilada y mata el
proceso al no encontrar `phontab`. Por debajo, funciona.

| Longitud de la ruta a `espeak-ng-data` | Resultado |
| --- | --- |
| 67 (venv en `/private/tmp/pp`) | OK — `tˈɛl mˌiːʲ ɐbˌaʊt ðə lˈæst tɹˈɪp juː tˈʊk.` |
| 101 / 131 / 151 | OK |
| 161 / 171 | Falla y sale del proceso |

Es el issue [#272](https://github.com/OHF-Voice/piper1-gpl/issues/272) de
piper1-gpl, abierto el 2026-08-15, con el PR
[#281](https://github.com/OHF-Voice/piper1-gpl/pull/281) sin fusionar: *«Stop
espeak-ng from truncating the data dir path»*.

Consecuencias, todas buenas:
- En un contenedor la ruta es `/usr/local/lib/python3.13/site-packages/piper/espeak-ng-data`,
  unos 60 caracteres. Muy por debajo del límite.
- **Piper funciona también en macOS.** El adaptador se puede escribir y probar
  aquí, sin Docker, antes de tocar ningún servidor.
- Piper solo añade `pathvalidate` como dependencia nueva: `onnxruntime` ya está
  en el árbol porque lo arrastra faster-whisper.
- Hay que fijar en el Dockerfile una ruta de instalación corta y una prueba que
  falle si `len(str(ESPEAK_DATA_DIR)) >= 160`. Es un fallo que reaparece solo
  con mover el proyecto de sitio.

### Oracle Cloud recortó el free tier y excluye Chuncheon ❌
La recomendación anterior ya no se sostiene:
- Desde el **15 de junio de 2026**, Always Free ARM bajó de 4 OCPU / 24 GB a
  **2 OCPU / 12 GB**.
- La doc oficial excluye explícitamente **South Korea North (Chuncheon)** de la
  creación de instancias Ampere A1.

Sigue habiendo 200 GB de disco y queda Seúl (South Korea Central), que no está
en la lista de exclusión — pero son 2 núcleos, y eso es justo lo que decide si
Whisper llega o no.

### Benchmark oficial de faster-whisper ✅
De su propio README, modelo `small`, int8, beam 5, **8 hilos de un i7-12700K**,
sobre 13 minutos de audio:

| Configuración | Tiempo | RAM |
| --- | --- | --- |
| int8 | 1m42s (≈7.6× tiempo real) | 1477 MB |
| int8, `batch_size=8` | 51s (≈15×) | 3608 MB |

Dos lecturas que importan aquí. La primera: `medium` cuesta del orden del triple
que `small`, y 2 núcleos Ampere rinden bastante menos que 8 hilos de un
i7-12700K, así que `medium` en el free tier es muy probablemente inviable — no
por RAM, que sobra, sino por núcleos. La segunda: `BatchedInferencePipeline`
duplica la velocidad a cambio de RAM, y con 12 GB la RAM no es el problema.
`adapters/stt.py:61` no lo usa hoy. Es la palanca más barata que hay.

## Lo que impide arrancar hoy

| # | Qué | Dónde | Consecuencia |
|---|---|---|---|
| 1 | TTS = macOS `say` | `adapters/tts.py:25` | No hay imagen Linux posible |
| 2 | Whisper `medium`, sin `cpu_threads` ni batching | `config.py:12`, `stt.py:31` | En 2 núcleos ARM, casi seguro más lento que el examen |
| 3 | Session id = marca de tiempo | `store.py:28` | `20260824-140338` se adivina: cualquiera abre el informe de otro |
| 4 | Estado en `data/` del contenedor | `serve.py:21` | Un redeploy borra los exámenes |
| 5 | Sin TLS | — | `getUserMedia` (`recorder.js:12`) no arranca fuera de contexto seguro. Sin HTTPS no hay micrófono |
| 6 | Un worker, lock de fichero | `serve.py:60`, `worker.py:80` | Un examen a la vez. Decisión defendible, pero tiene que verse en la interfaz |

## Dónde

Con el recorte de Oracle y el cumplimiento fuera del alcance, el argumento de
«servidor en Corea» se queda solo en latencia — y esta aplicación sube un blob
de ~1 MB por respuesta, no hace nada interactivo. La latencia casi no importa;
los núcleos sí.

| Opción | Coste | Núcleos | Nota |
| --- | --- | --- | --- |
| **Oracle Free, Seúl** | 0€ | 2 ARM | Gratis y en Corea. Obliga a `small` + batching, y hay que confirmarlo con T0. Capacidad ARM irregular |
| **Hetzner CPX31, Singapur o Alemania** | ~16–25€ | 4 AMD | El doble de núcleos y bastante más rápidos por núcleo. Se pasa un poco del límite tras la subida de precios del 15/06/2026 |
| Vultr Seoul 4 vCPU / 8 GB | $40 | 4 | Fuera de presupuesto |
| AWS Lightsail Seoul | $10–20 | 2 | Los planes baratos se quedan en 2 GB de RAM |

Recomendación: **empezar en Oracle Free (Seúl) y dejar que T0 decida**. Si
`small` con batching no llega, Hetzner CPX31 es la salida, y la diferencia son
20€ al mes. Ninguna de las dos decisiones bloquea a la otra: la imagen es la
misma.

## Tareas

### T0 — Medir, que es lo que decide máquina y modelo (medio día)

Sobre las 15 respuestas guardadas en `data/sessions/20260820-145223`, medir
segundos de proceso por minuto de audio para cuatro combinaciones:
`small` y `medium`, cada uno con y sin `BatchedInferencePipeline`, con
`cpu_threads` fijado al número de núcleos de la caja.

El listón no es abstracto: el worker evalúa mientras el candidato sigue
respondiendo, y llegan unos 90 s de audio cada dos o tres minutos. Basta con ir
por encima de ~1× tiempo real con holgura; por debajo, la cola crece durante
todo el examen y el informe aparece mucho después del final.

Si hay que bajar a `small`, el bench decide si se puede: los valores de VAD en
`config.py:24` están medidos contra `evidence/sample-answer.wav`, y el propio
comentario documenta que con otros valores `pause_ratio` se hunde a 0.02.
Comparar sobre las mismas 15 respuestas: transcripción, `pause_ratio`,
`mean_utterance_length` y nivel final.

Medir también RAM residente. Con batching sube a ~3.6 GB según el benchmark, y
eso descarta cualquier plan de 2 GB.

### T1 — Que arranque en Linux (2–3 días)

- `PiperTextToSpeech` junto a `SayTextToSpeech`, mismo puerto, misma caché
  direccionada por contenido, misma escritura por rename.
  **Se puede escribir y probar en el Mac**, sin Docker.
- Selección por entorno, calcada de `config.backend()`: `OPIC_TTS=say|piper`.
- Prueba que falle si la ruta de `espeak-ng-data` llega a 160 caracteres, con el
  issue #272 citado al lado. Sin ella, mover el proyecto de carpeta rompe el TTS
  con un error que apunta a otro sitio.
- Corregir la nota de `config.py:6` y §6 bis del documento de diseño: la razón
  que dan para descartar Piper no es la real.
- La clave de la caché incluye la voz (`tts.py:11`), así que pasar de `say` a
  Piper la invalida entera. Una regeneración, nada más, pero conviene saberlo.
- Dockerfile con ffmpeg, ruta de instalación corta, y el modelo de Whisper **en
  el volumen, no en la imagen** (`medium` son ~1.5 GB). `stt.py:41` ya carga
  perezoso; basta apuntar la caché al volumen y precalentarla una vez.
- Probar los dos formatos de grabación: Safari de iOS da `mp4`/AAC y Chrome da
  `webm`/Opus (`recorder.js:39`). Es el fallo que solo aparece con el móvil de
  otra persona.

Terminado = un examen completo dentro del contenedor, con informe.

### T2 — Que un examen no sea legible por extraños (1 día)

- `new_session_id` → `secrets.token_urlsafe(16)`. Deja de ser ordenable, así que
  la fecha pasa a `session.json` y el listado ordena por ella.
- Cookie al crear la sesión; sin ella, 404 en `/api/sessions/{id}`, en el audio y
  en el informe. 404 y no 403: un 403 confirma que el id existe.

### T3 — Que los datos sobrevivan a un deploy (1 día)

- Volumen persistente. `SESSIONS` y `TTS_CACHE` (`serve.py:21`) son hoy rutas
  relativas al directorio de trabajo; pasan a leerse del entorno.
- Copia a Cloudflare R2 por `cron`.
- Retención: borrar el audio a los N días, conservar `result.json` y
  `report-ko.html`. En el free tier el disco es de los 200 GB, no ilimitado.

### T4 — La cola, explícita (1–2 días)

`serve.py:60` documenta bien por qué hay un solo proceso. Eso no cambia; lo que
cambia es que el usuario lo vea:
- Posición en cola y espera estimada en `/api/sessions/{id}/progress`.
- Rechazar un examen nuevo mientras otro corre, con mensaje claro.
- `worker.resume()` (`worker.py:333`) ya retoma tras un reinicio: probarlo
  matando el proceso a mitad de examen dentro del contenedor.

La transcripción ocurre en ctranslate2, en C++, que suelta el GIL, así que el
worker no debería congelar a FastAPI. Confirmarlo midiendo la latencia de
`/progress` con una transcripción en curso.

### T5 — Despliegue (1 día)

- Caddy delante, TLS automático. **No es opcional**: sin HTTPS no hay micrófono.
- `docker compose` con reinicio automático.
- Healthcheck que compruebe que el hilo del worker sigue vivo, no solo que
  FastAPI responde. Un worker muerto con la web en pie es el fallo silencioso
  más probable de este diseño.
- Logs a fichero con rotación.

### T6 — Barandillas (1 día)

- Tamaño y duración máximos por respuesta. Hoy `post_answer` (`app.py:267`)
  acepta lo que llegue, y con una sola cola un fichero enorme la bloquea entera.
- Límite de gasto y alerta en la clave de Anthropic.
- Rate limit por IP al crear sesiones.
- `ANTHROPIC_TIMEOUT_S` es 300 con reintentos (`worker.py:284`): revisar que el
  peor caso encadenado no bloquee la cola más que un examen entero.

## Orden

```
T0 (medir) ──> decide modelo y máquina
     └──> T1 (Piper + Docker) ──> T3 (volumen) ──> T5 (deploy) ──> T4, T6
T2 (session id): independiente, cuando quieras
```

T0 primero porque decide si la caja gratis sirve o hay que pagar 20€.
Y T1 se puede empezar hoy en el Mac, porque Piper ya está verificado.
