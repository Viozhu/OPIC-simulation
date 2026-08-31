# Multi-sesión, despliegue permanente y feedback — Diseño

Fecha: 2026-08-31
Estado: aprobado, pendiente de plan de implementación
Rama: `multi-session`

## 1. Objetivo

Tres cosas que hoy no se pueden hacer:

1. **Saber de quién es cada examen.** Hoy una sesión es una marca de tiempo y
   nada más. Con varios invitados, `data/sessions/` es una lista de fechas sin
   nombres.
2. **Que el examen esté en pie sin levantarlo a mano.** Hoy `tools/share.sh`
   abre un túnel efímero que muere con el script, y hay que ejecutarlo,
   vigilarlo y reenviar el enlace en cada ocasión.
3. **Recoger la opinión del candidato.** Hoy el examen termina en el informe y
   ahí se acaba; no hay forma de saber si la experiencia sirvió.

## 2. Alcance

Dentro:

- Un paso de identidad al principio: nombre y correo, escritos por el invitado.
- Ids de sesión no adivinables.
- Un túnel Cloudflare con nombre y dominio propio, servidor y túnel arrancados
  por `launchd`, supervivientes a un reinicio.
- Página de feedback al final del examen (1–5 y comentario) que aterriza en una
  hoja de Google.
- Barandillas mínimas que el hecho de estar en pie 24/7 vuelve obligatorias:
  límite de tamaño por respuesta, límite de creación de sesiones por IP,
  rotación del token.

Fuera, a propósito:

- **Paralelismo real.** Sigue habiendo un worker, una cola, un examen a la vez.
  Lo que se pide es que haya muchos exámenes *a lo largo del tiempo* y que se
  puedan encontrar, no que dos personas graben a la vez.
- **Linux, Piper y Docker.** El plan de `2026-08-24-deployment-and-monetization.md`
  sigue vigente y sin ejecutar. Este documento no lo sustituye ni lo contradice:
  elige el Mac por ser el camino con menos trabajo, no por ser el mejor destino.
- Autenticación de verdad, cuentas, cobro.
- Panel de administración.

## 3. Decisiones tomadas

| Decisión | Elección | Razón |
| --- | --- | --- |
| Dónde corre | Mac propio + túnel Cloudflare con nombre | Cero trabajo de adaptadores: `say` y Whisper `medium` siguen igual. Un destino Linux exige Piper, un benchmark de Whisper, Docker, volumen y Caddy — una semana — y el Mac de todos modos tiene la CPU más rápida de las tres opciones |
| Quién escribe el correo | El invitado, en la primera pantalla | Un enlace permanente sirve para todos. La alternativa —un enlace por invitado— obliga a ejecutar un comando por persona, que es justo lo que se quiere dejar de hacer |
| Concurrencia | Uno a la vez, sin tocar la cola | Confirmado con el usuario. `worker.py` documenta por qué la cola es única y esa razón no ha cambiado |
| Cómo se encuentra un examen | La hoja de Google + un comando de consola | La hoja ya lleva correo, nivel y enlace al informe: es el índice. Un endpoint de listado le daría a cualquier invitado la lista de todos los demás, porque todos comparten el mismo token |
| Escritura en Sheets | Webhook de Apps Script | Sin proyecto de GCP, sin fichero de credenciales, sin dependencia nueva: `urllib.request` de la biblioteca estándar. El coste es que la URL es el secreto entero |
| Id de sesión | `secrets.token_urlsafe(16)` | Ver §5. No es una mejora estética: con un nombre de máquina permanente, una marca de tiempo es adivinable |

## 4. Identidad

### 4.1 Un paso nuevo, el primero

`Step.IDENTITY` se antepone a `ORDER` en `session/state.py`, y
`SessionState.new` empieza ahí en vez de en `SURVEY`.

Las sesiones ya guardadas no se rompen: `ORDER` solo define qué paso sigue a
cuál, y ninguna de las catorce está en `IDENTITY`. Una sesión antigua en
`SURVEY` avanza exactamente como antes.

### 4.2 Los datos

```python
@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    email: str
```

`SessionState.candidate: Candidate | None`. `store.from_json` lo lee con
`.get("candidate")`, que devuelve `None` para las sesiones existentes.

### 4.3 El endpoint

`PUT /api/sessions/{id}/identity`, con el mismo patrón que
`put_survey` y `put_level`: valida, llama a `worker.update`, devuelve el estado.

La validación es deliberadamente mínima: nombre no vacío, correo con una `@` y
sin espacios, ambos por debajo de 200 caracteres. **No se verifica el correo.**
Un correo con una errata es un problema del invitado, y una comprobación de
entrega no compra nada aquí: el correo es una etiqueta para encontrar el
examen, no una credencial ni un canal.

### 4.4 La pantalla

`static/steps/identity.js`, en coreano como el resto de lo que ve el
candidato, con el mismo patrón de los otros módulos de paso. Se registra en la
lista de `app.js` que importa los pasos.

## 5. Ids de sesión: el fallo que abre el despliegue permanente

`new_session_id` devuelve hoy `%Y%m%d-%H%M%S` (`store.py:29`). Con el túnel
efímero eso era tolerable, porque el nombre de máquina moría con el script.

Con un nombre permanente deja de serlo: **una marca de tiempo se adivina.**
Cualquiera que tenga el enlace puede recorrer fechas y horas y leer el informe
de otro candidato — nombre, correo, transcripciones, nivel. `GET
/api/sessions/{id}` no comprueba nada, y así está documentado en la propia
skill `share-test`.

Hay además un segundo fallo, menor y real: dos sesiones creadas en el mismo
segundo comparten carpeta, porque `store.create` hace `mkdir(exist_ok=True)`.
Una pisa a la otra.

Ambos se cierran con el mismo cambio:

```python
def new_session_id() -> str:
    return secrets.token_urlsafe(16)
```

Consecuencias, todas hay que atenderlas:

- **El id deja de ser ordenable.** La fecha pasa a `SessionState.created_at`,
  guardada en `session.json`. `store.list_unfinished` ordena por ese campo en
  vez de por nombre de carpeta.
- **Las catorce sesiones existentes no tienen `created_at`.** Al leerlas, si el
  campo falta, se deriva del nombre de la carpeta cuando encaja con el formato
  antiguo, y de la fecha de modificación del fichero cuando no. Sus carpetas no
  se renombran: los informes ya emitidos siguen abriéndose por su ruta.
- `store.create` pasa a `mkdir(exist_ok=False)`; una colisión —imposible en la
  práctica con 128 bits— sería un error ruidoso, no una carpeta compartida.

**Lo que este cambio no resuelve, y hay que decirlo:** el id pasa a ser una
credencial al portador. Quien tenga la URL de un examen, lo lee. Con un
invitado a la vez y enlaces enviados uno a uno eso es aceptable, y añadir una
cookie de propiedad introduciría un modo de fallo peor —el invitado que borra
cookies a mitad de examen se queda fuera del suyo— a cambio de poco. Si algún
día hay varios invitados simultáneos, la cookie de propiedad del plan T2 vuelve
a la mesa.

## 6. Encontrar un examen

Sin panel y sin endpoint de listado, por la razón de §3: todos los invitados
comparten el mismo token, así que un listado se los enseña todos a cualquiera.

Dos vías, ninguna nueva superficie de red:

- **La hoja de Google.** Cada examen terminado escribe una fila con fecha,
  nombre, correo, nivel final y enlace al informe. Es el índice, y ya se
  construye para §8.
- **La consola, en la máquina.** `uv run python -m opic.cli --find <texto>`
  recorre `data/sessions/*/session.json` y lista las sesiones cuyo nombre o
  correo contienen el texto, con su fecha, su paso y su nivel si lo tiene.
  Catorce sesiones hoy; el recorrido es trivial hasta varios miles.

## 7. Despliegue permanente

### 7.1 El túnel

Túnel Cloudflare **con nombre**, no `quick`. El dominio ya está en Cloudflare.

- `cloudflared tunnel create opic` deja las credenciales en `~/.cloudflared`.
- Un registro DNS `CNAME` apunta `opic.<dominio>` al túnel.
- `~/.cloudflared/config.yml` mapea ese nombre a `http://localhost:8000`.

El nombre de máquina deja de cambiar en cada arranque, que es lo que hoy obliga
a reenviar el enlace.

### 7.2 Los dos servicios

Dos agentes de `launchd`, ambos con `KeepAlive` y `RunAtLoad`, plantillas en
`tools/deploy/`:

- `com.opic.server` — `uv run uvicorn --factory opic.web.serve:app`, con el
  directorio de trabajo del repositorio y `OPIC_SHARE_TOKEN` leído de un
  fichero fuera de git, no del entorno interactivo.
- `com.opic.tunnel` — `cloudflared tunnel run opic`.

`pmset` para que la máquina no se duerma. Registro a fichero con rotación: hoy
la salida del servidor vive en la terminal desde la que se lanzó, y un servicio
de `launchd` no tiene ninguna.

### 7.3 Salud

`GET /healthz` **montado antes de la puerta**, para que un vigilante externo
pueda consultarlo sin el token. Devuelve `ok` y nada más — ni versión, ni
sesiones, ni el nombre del modelo.

Comprueba que **el hilo del worker sigue vivo**, no solo que FastAPI responde.
Un worker muerto con la web en pie es el fallo silencioso más probable de este
diseño: el candidato hace el examen entero y nada se transcribe.

### 7.4 Lo que empeora al estar siempre en pie, y qué se hace

La skill `share-test` justifica su único secreto así: «lo que lo hace
suficientemente seguro es que vive un examen: el nombre de máquina es nuevo en
cada arranque y muere con el script». **Este documento borra las dos mitades de
esa frase.** Lo que queda es un secreto compartido delante de una aplicación
sin noción de propietario, que gasta crédito de Anthropic, expuesta a
todas horas.

Mitigaciones, todas dentro del alcance:

| Riesgo | Medida |
| --- | --- |
| El enlace se filtra y alguien crea exámenes con tu crédito | Límite de creación de sesiones por IP en `POST /api/sessions` |
| Un fichero enorme bloquea la cola entera | Tamaño y duración máximos en `post_answer`, que hoy acepta lo que llegue |
| El token se filtra y no caduca | Rotación: el token sale de un fichero, cambiarlo y recargar el agente invalida las cookies vivas |
| Gasto desbocado | Límite de gasto y alerta en la clave de Anthropic, fuera del código |

La cookie sigue durando doce horas y la puerta sigue devolviendo 404, no 403.

## 8. Feedback y hoja de cálculo

### 8.1 Dónde vive

No hay paso nuevo. El examen ya termina en `Step.DONE`; la tarjeta de feedback
se añade al final de `static/steps/done.js`, debajo del enlace al informe. Un
paso más en la máquina de estados obligaría a que el candidato «avance» después
de haber terminado, que es exactamente lo que no es.

Pregunta una valoración de 1 a 5 y un comentario libre (hasta 2000 caracteres),
en coreano. Una vez enviada, la tarjeta muestra el agradecimiento en lugar del
formulario.

### 8.2 El camino de los datos

`POST /api/sessions/{id}/feedback`:

1. **Escribe `session.json` primero.** El feedback está guardado antes de que
   Google entre en la historia.
2. Encola una tarea `PUBLISH` en el worker existente, que ya sabe reintentar.
3. Responde.

El envío del candidato no espera a Google y no falla por Google. Si la hoja no
contesta, el feedback está en disco con `published: false` y se reintenta.

### 8.3 El adaptador

`SheetSink` como protocolo en `core/ports.py`, junto a los otros puertos:

```python
class SheetSink(Protocol):
    def append(self, row: dict[str, str]) -> None: ...
```

`adapters/sheets.py` lo implementa contra el webhook de Apps Script con
`urllib.request` de la biblioteca estándar. **Sin dependencia nueva.**

Selección por entorno, con el mismo patrón que `OPIC_LLM`: si `OPIC_SHEET_URL`
no está, el sumidero es nulo y no se envía nada. Así las pruebas y cualquier
ejecución local no escriben en la hoja de nadie, sin condicionales repartidos
por el código.

### 8.4 La fila

| Columna | Origen |
| --- | --- |
| Fecha y hora | `created_at` de la sesión |
| Nombre | `candidate.name` |
| Correo | `candidate.email` |
| Id de sesión | `state.id` |
| Nivel final | `result.json`, vacío si el examen no llegó a graduarse |
| Valoración 1–5 | El formulario |
| Comentario | El formulario |
| Enlace al informe | `OPIC_PUBLIC_URL` + la ruta del informe |

`OPIC_PUBLIC_URL` es una variable nueva: el servidor no puede saber por sí
mismo bajo qué nombre público lo ven desde fuera.

### 8.5 Reintento manual

`uv run python -m opic.cli --publish <session>` construye la fila y la envía.
Sirve para un examen anterior a esta función y para uno cuyo envío falló y
agotó los reintentos.

## 9. Pruebas

Ninguna prueba toca la red ni la hoja de verdad.

- **Unitarias puras:** generación de ids, `created_at` derivado de una sesión
  antigua sin el campo, la transición `IDENTITY → SURVEY`, la validación del
  correo, la construcción de la fila a partir de un estado y un resultado.
- **Con doble:** la tarea `PUBLISH` contra un `SheetSink` falso que registra lo
  recibido, y otro que lanza, para comprobar el reintento y la marca
  `published: false`.
- **De endpoint,** con `TestClient`: identidad, feedback, `/healthz` accesible
  sin token, `/api/sessions/{id}` con un id inexistente devolviendo 404.
- **De compatibilidad:** cargar las catorce sesiones de `data/sessions` con el
  código nuevo y comprobar que ninguna revienta ni pierde datos.

Marcadas con `models` y por tanto excluidas por defecto: un examen completo de
extremo a extremo contra el servidor real.

## 10. Orden de trabajo

```
A. Identidad + ids nuevos + created_at   ← todo lo demás depende del esquema
        │
        ├──> B. Feedback + adaptador de hoja + fila + --publish
        │
        └──> C. Despliegue: túnel con nombre, launchd, /healthz, barandillas
```

A primero, porque cambia la forma de `session.json` y B y C escriben encima. B
y C son independientes entre sí. C se cierra el último porque exponer
permanentemente algo cuyos ids son adivinables sería empeorar el problema, no
resolverlo.

## 11. Lo que este diseño no resuelve

- **Sigue habiendo un examen a la vez.** Dos invitados simultáneos hacen cola,
  y hoy la interfaz no lo dice. Aceptado por ahora; el T4 del plan de despliegue
  cubre hacerlo visible cuando haga falta.
- **Depende de tu Mac y de tu línea.** Si la máquina se duerme, se reinicia sin
  sesión iniciada o se cae internet, el examen deja de existir hasta que
  vuelvas. Ese es el precio exacto de no haber ido a Linux.
- **Un examen es legible por quien tenga su URL.** Ver §5.
- **El correo no está verificado.** Dos personas pueden escribir el mismo, y
  una puede escribir el de otra.
