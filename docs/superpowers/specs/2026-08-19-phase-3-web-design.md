# Fase 3 — Interfaz web y evaluación en paralelo

Fecha: 2026-08-19
Estado: aprobado, pendiente de plan de implementación

Continúa `2026-08-19-opic-simulator-design.md` (diseño maestro) y
`2026-08-19-phase-2-adapters-design.md`. Donde este documento contradice al
maestro, manda este, y la contradicción está justificada en el propio texto.

## 1. Objetivo

Que un candidato haga el examen completo en el navegador —los cinco pasos,
hablando por micrófono— y reciba su nivel sin tocar la línea de comandos.

## 2. Alcance

Dentro:

- Los cinco pasos en el navegador, con grabación real y reproducción del TTS.
- Persistencia de la sesión, reanudable tras recargar la página o reiniciar el
  servidor.
- Evaluación en segundo plano, arrancada durante el examen, con pantalla de
  progreso (채점 중).
- Resultado en crudo al terminar: nivel ACTFL y el JSON de las dimensiones.
- Reescritura de `cli.py` sobre la nueva capa de sesión.

Fuera:

- El informe presentable, con desglose por dimensiones, citas y proxy de
  pronunciación. Es la Fase 4.
- Los audios de muestra del Self Assessment: no existe el material.
- Histórico entre sesiones, SQLite, gráficas de progreso.
- Multiusuario y autenticación. Un usuario, una máquina.

## 3. Decisiones tomadas

| Decisión | Elección | Razón |
|---|---|---|
| Alcance de la fase | Examen + evaluación con 채점 중; informe a la Fase 4 | Deja el ciclo cerrado sin la CLI |
| Persistencia | Ficheros JSON por sesión, no SQLite | El histórico está fuera de alcance; YAGNI |
| Ejecución del trabajo | Un hilo en el proceso de FastAPI, reanudable | Un solo proceso, como el maestro |
| Momento de evaluar | En paralelo al examen, respuesta a respuesta | 75 min medidos; la espera baja a ~35 |
| Reparto cliente/servidor | Una página, JS que gobierna los cinco pasos | La máquina de estados del test no se parte |
| Progreso | Sondeo HTTP cada 3 s, no WebSocket | Dos números que cambian cada 4 min |
| Fidelidad visual | Mismo flujo, estética propia | El material de `evidence/` es de terceros |
| Reglas de grabación | Fiel al OPIc: sin re-grabar, 재생 una vez | Es la presión que hay que entrenar |
| Formato de audio | `webm/opus` guardado tal cual | faster-whisper lo decodifica; una etapa menos |
| Verificación | API con dobles + checklist manual | Sin Chromium: el disco es la limitación |

## 4. Corrección: la evaluación dura ~75 minutos

El plan de la Fase 2b arrastraba una estimación de 25-35 minutos. La medición
de `notes/2026-08-19-rater-model.md` la desmiente: cinco llamadas a `rate` con
`qwen3:14b` promediaron **253 s (~4,2 min)**. Quince preguntas son unos **63
minutos de rating**, más unos 12 de transcripción: **~75 minutos**.

De ahí sale la decisión central de esta fase. Si la evaluación esperase al
final del examen, el candidato miraría una pantalla durante hora y cuarto.
Evaluando en paralelo —cada respuesta entra en la cola en cuanto se graba— al
terminar el examen (~40 min) ya están puntuadas siete u ocho —unos 5 min por
respuesta entre transcripción y rating— y lo que queda son unos 35 minutos.

Durante el examen no se ejecuta ningún modelo *en el camino crítico*: el audio
de las preguntas ya está sintetizado desde el Setup, así que el trabajo de
fondo no puede hacer esperar a nadie. Esto matiza el "durante el examen no
interviene ningún LLM" del diseño maestro: sí interviene, pero nunca entre que
el candidato pulsa 다음 y aparece la pregunta siguiente.

## 5. Arquitectura

Tres piezas nuevas. Ninguna dentro de `core/`.

    src/opic/
    ├─ core/            sin cambios
    ├─ adapters/        sin cambios
    ├─ session/
    │   state.py        SessionState y sus transiciones legales
    │   store.py        leer/escribir data/sessions/<id>/, escritura atómica
    │   worker.py       la cola de trabajo y sus tareas
    └─ web/
        app.py          FastAPI: rutas, validación, delegación
        static/         app.js y steps/*.js, módulos ES nativos, sin build
        templates/      index.html

`web/app.py` no sabe puntuar ni generar preguntas: recibe, valida contra el
estado, delega en `session/` y devuelve JSON. `session/worker.py` es el único
módulo que toca los adaptadores de IA. Esa frontera es lo que permite que los
tests de la API corran con dobles y sin modelos cargados.

La regla del maestro sigue en pie y se amplía: `core/` no importa `fastapi`,
ni los adaptadores, ni `session/`.

### 5 bis. `cli.py` se reescribe encima

`run_exam` lleva hoy su propio bucle y su propio formato de escritura. Si la
web estrena otro, quedan dos caminos que se desvían en silencio: un cambio en
el formato de `answer-NN.json` arreglaría uno y rompería el otro sin que nadie
se entere. La última tarea de la fase reescribe `cli.py` sobre `session/`,
conservando su interfaz de línea de comandos y sus tests actuales.

## 6. La sesión en disco

Una carpeta por sesión. `session.json` es la fuente de verdad.

    data/sessions/<id>/
      session.json          paso actual, survey, nivel, preguntas, estado por respuesta
      answer-NN.webm        lo grabado por el navegador
      answer-NN.json        transcript, métricas y dimensiones
      result.json           sólo cuando están las quince

El audio de las preguntas **no se copia aquí**: ya vive en `data/tts_cache/`
indexado por hash del texto, y `session.json` guarda esa ruta. Copiarlo sería
duplicar quince ficheros por sesión en una máquina donde el disco es la
limitación conocida.

`<id>` es la marca de tiempo de creación: `20260819-143052`. Legible,
ordenable, sin dependencia nueva.

`session.json` se escribe entero y se publica por `rename`, igual que ya hace
el caché de TTS: nunca se lee un fichero a medio escribir.

Cada respuesta lleva su propio estado —`recorded`, `transcribed`, `scored`,
`failed`— y ahí se apoya la reanudación. No hace falta más maquinaria que
mirar qué ficheros existen y en qué estado quedó cada respuesta.

`state.py` declara las transiciones legales del paso de examen
(`survey → level → setup → sample → test → grading → done`) y rechaza el resto.
El servidor no confía en el orden que proponga el navegador.

## 7. La API

| Ruta | Qué hace |
|---|---|
| `POST /api/sessions` | Crea la sesión y devuelve su `<id>`; el navegador lo guarda en `localStorage` |
| `GET /api/sessions/{id}` | El estado completo; es lo primero que pide el JS al cargar |
| `GET /api/survey` | El schema del survey en coreano, desde `core/survey.py` |
| `PUT /api/sessions/{id}/survey` | Valida con `validate_survey`; devuelve los `ValidationIssue` |
| `PUT /api/sessions/{id}/level` | Fija el self assessment y encola la generación de preguntas y audio |
| `GET /api/sessions/{id}/questions/{n}/audio` | Sirve el audio; 404 mientras no exista |
| `POST /api/sessions/{id}/answers/{n}` | Guarda el `webm` y encola su evaluación; responde sin esperar al modelo |
| `GET /api/sessions/{id}/progress` | Transcritas, puntuadas, fallidas, y si ya hay `result.json` |

Los textos coreanos de la interfaz salen de `core/`, no del HTML: la UI no
duplica el contenido del survey ni los seis niveles del self assessment.

**Por qué sondeo y no WebSocket.** El maestro pedía un WebSocket para el
progreso. Lo que viaja son dos contadores que cambian cada cuatro minutos. Un
`GET` cada 3 s es menos código, sobrevive a que el portátil se duerma sin
lógica de reconexión, y no obliga a mantener estado por conexión. Si la Fase 4
quiere el informe en vivo, se reconsidera entonces.

## 8. El recorrido

1. **Survey.** Cuatro partes. Contador de doce ítems en vivo, como el original.
   La validación es la de `core/survey.py`; los errores se pintan junto a su
   campo.
2. **Self Assessment.** Seis niveles, cada uno con su descripción coreana. **Sin
   audio de muestra**: el original acompaña cada nivel con una grabación de
   ejemplo y no tenemos ese material —grabarlo son seis muestras de seis niveles
   distintos de inglés hablado, que no es algo que esta fase pueda fabricar—. La
   descripción es la que decide, como en el examen real. `sample_audio_id` ya
   está en `SelfAssessOption` esperando a que existan. Al elegir, se
   encola la generación: blueprint, las quince preguntas en una llamada al
   escritor, y la síntesis de los quince audios.
3. **Setup.** Prueba de micrófono: grabar, reproducir, confirmar. Aquí se pide
   el permiso del navegador, una sola vez, antes de que importe.
4. **Sample Question.** Una pregunta que no puntúa, con la mecánica completa.
5. **Test.** Si al llegar faltan preguntas o audios, pantalla 준비 중 hasta que
   estén.

En el test, por pregunta: se reproduce el audio, al terminar arranca
`MediaRecorder`, el candidato pulsa 다음 cuando acaba de hablar, el `webm` se
sube y se pasa a la siguiente. 재생 disponible **una sola vez**. No se puede
re-grabar ni volver atrás. **No hay cronómetro**: ni por respuesta ni global.
El OPIc real da unos 40 minutos para el conjunto, pero un reloj en pantalla es
una decisión de producto que esta fase no necesita tomar y que la Fase 4 puede
añadir sin tocar nada de lo de aquí.

Al pulsar 다음 en la última: pantalla 채점 중 con progreso y estimación. Se puede
cerrar la pestaña; al volver a la aplicación se recupera la sesión y su
progreso desde disco.

## 9. El worker

Un hilo, una cola, tareas heterogéneas: `generate_questions`,
`synthesize_question(n)`, `evaluate_answer(n)`, `aggregate`.

Que compartan cola no es pereza: es lo que garantiza que la generación de
preguntas y la evaluación de la primera respuesta nunca pidan a Ollama a la
vez. Con el 14B cargado en 24 GB, dos peticiones concurrentes es exactamente
el escenario que produjo los timeouts de 600 s documentados en la nota del
rater. Serializado por construcción.

`evaluate_answer(n)`: `transcribe` → `compute_metrics` → `rate` → escribir
`answer-NN.json`. Cuando las quince están resueltas, `aggregate` → `result.json`.
El worker no mantiene en memoria nada que no esté también en disco.

**Reanudación.** Al arrancar, el servidor recorre `data/sessions/`, busca las
sesiones sin `result.json` y reencola lo que le falte a cada una según el
estado de sus respuestas.

**Un solo worker de uvicorn.** Dos procesos serían dos colas peleando por el
mismo modelo y por los mismos ficheros. Va escrito en el README y comprobado
al arrancar.

## 10. Cuando algo falla

| Fallo | Comportamiento |
|---|---|
| Rating malformado | La respuesta queda `failed`; el examen sigue. El resultado declara sobre cuántas respuestas se calculó |
| Ollama no responde | Tres reintentos con espera creciente, luego `failed`. El progreso lo dice en coreano |
| La subida del audio falla | El JS reintenta tres veces; después avisa y ofrece reintentar, con el blob todavía en memoria |
| Micrófono denegado | Se detecta en el Setup, con instrucciones. Nunca a mitad del test |
| Recarga durante el test | Se retoma en la pregunta actual; la respuesta a medio grabar se pierde, y la pantalla lo advierte de antemano |
| Ninguna respuesta puntuada | No se escribe `result.json`; la pantalla explica qué falló en vez de mostrar un nivel inventado |

## 11. Verificación

- **`tests/session/`** — store y máquina de estados. Puro y en milisegundos:
  transiciones ilegales rechazadas, escritura atómica, reanudación desde una
  carpeta a medio construir armada a mano.
- **`tests/web/`** — `TestClient` recorriendo los cinco pasos con dobles de los
  cuatro puertos, incluida la subida de un `webm` de fixture real y su paso a
  `scored`.
- **`tests/test_core_purity.py`** — se le añade que `core/` no importa
  `fastapi` ni `session`.
- **Checklist manual**, escrita en el plan, para lo que ningún test cubre: el
  permiso del micro, que el audio de la pregunta suene, que 재생 sólo funcione
  una vez, y una sesión completa contra los modelos reales.

El fixture `webm` se graba una vez con el navegador y se versiona. No vale un
`wav` renombrado: el punto de la prueba es que el formato que produce
`MediaRecorder` atraviesa el pipeline.

La prueba de aceptación de la fase: una sesión completa en el navegador,
grabada con la voz del usuario, que termina con un nivel ACTFL en pantalla.

## 12. Riesgos

**La evaluación en paralelo hace que la máquina vaya justa durante el examen.**
El camino crítico no toca los modelos, así que el efecto esperado es un
portátil caliente y un ventilador, no una pregunta que se retrasa. Si la
grabación se degrada, la mitigación es una línea: dejar de encolar hasta que
termine el examen.

**`MediaRecorder` no es igual en todos los navegadores.** El objetivo declarado
es Chrome en macOS. Safari produce `mp4` en vez de `webm`; se detecta el tipo
soportado y se guarda con la extensión correcta, ya que Whisper decodifica
ambos.

**El tiempo de generación de preguntas no está medido.** Setup y Sample dan
unos 2-3 minutos de cobertura; una llamada al 14B con schema forzado podría
tardar más. La pantalla 준비 중 lo absorbe sin romper nada, pero la primera tarea
del plan debe medirlo, igual que se midió el rater.

**Un `session.json` corrupto deja la sesión inservible.** Se mitiga con la
escritura por `rename` y aceptando la pérdida: es una sesión local de un solo
usuario, no un sistema con obligación de durabilidad.

## 13. Criterios de éxito

- Una sesión completa se hace en el navegador, de principio a nivel final.
- Cerrar la pestaña a mitad de la evaluación y volver recupera el progreso.
- Reiniciar el servidor a mitad de la evaluación la reanuda donde estaba.
- Una respuesta que el modelo puntúa mal no impide terminar el examen.
- Los tests de `core/` siguen corriendo en menos de un segundo sin modelos.
- Los tests de la web corren sin Ollama, sin Whisper y sin navegador.
- El equipo puede estar desconectado de internet.
