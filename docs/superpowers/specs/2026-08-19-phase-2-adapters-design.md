# Fase 2 — Adaptadores locales y reparación de interfaces

Fecha: 2026-08-19
Estado: aprobado, pendiente de plan de implementación
Antecede: `2026-08-19-opic-simulator-design.md` (Fase 1, motor `core/`)

## 1. Objetivo

Conectar el motor puro con los tres modelos locales —Piper para sintetizar las
preguntas, faster-whisper para transcribir las respuestas, Qwen3 vía Ollama para
juzgarlas— y reparar los cuatro tipos de `core/` que hoy prometen más de lo que
pueden cumplir.

Al terminar esta fase, un examen completo se puede ejecutar de principio a fin
desde la línea de comandos y producir un informe en coreano con nivel ACTFL. Sin
navegador. La Fase 3 le pondrá interfaz a algo que ya funciona.

## 2. Alcance

Dentro:

- Los cuatro cambios de interfaz que la revisión final de la Fase 1 identificó.
- Métricas de pausa y enunciado recalculadas sobre datos que Whisper sí entrega.
- Tres puertos declarados en `core/` y sus tres implementaciones en `adapters/`.
- Un recorrido de examen completo por línea de comandos.

Fuera:

- Interfaz web, captura desde el navegador, pantalla de 채점 중. Fase 3.
- Persistencia en SQLite. Los resultados se escriben a disco como JSON; el
  esquema relacional llega cuando haya sesiones que reanudar.
- Seguimiento de progreso entre exámenes.
- Cualquier proveedor de IA remoto.

## 3. Lo que midió el spike y que gobierna este diseño

Tres hallazgos empíricos, obtenidos sobre 90 segundos de habla espontánea no
nativa (`evidence/sample-answer.wav`, con su transcripción en
`evidence/sample-transcript.json`).

### 3.1 Whisper repara la gramática si se le deja

Con ajustes por defecto, el modelo inserta sujetos que el hablante omitió
("**it** was so beautiful") y normaliza los verbos a pasado correcto
("we **came**", "we **ate**"). Con `condition_on_previous_text=False` y
`temperature=0.0`, los preserva.

La mitigación no es una optimización: es la condición que hace evaluable la
gramática. Sin ella desaparecen alrededor de cinco errores cada noventa
segundos, justo los que el informe debe citar.

Bajar a `small` empeora las dos cosas a la vez: destroza contenido
("Jeju-do is in East Island") y además repara en los puntos que importan. El
tamaño `medium` queda fijado.

Rendimiento en caliente: 48 s por respuesta de 90 s, es decir unos 12 minutos
para los quince turnos de un examen.

### 3.2 El coreano de Qwen3 es utilizable; la velocidad del 14B no

El modelo de 14B produjo coreano natural y técnicamente correcto, JSON válido al
primer intento, las cinco dimensiones, y seis de seis citas textualmente
exactas. Esa última cifra era el riesgo real de pedirle evidencia a un modelo
local, y quedó despejado.

Pero rinde 2,8 tokens/s en un M2, unos 3,6 minutos por respuesta: casi una hora
de LLM por examen. El de 8B rinde 5,3 tokens/s, aunque en la prueba devolvió una
sola dimensión de las cinco por copiar el ejemplo del prompt en lugar de seguir
la instrucción.

### 3.3 Tres métricas quedan muertas contra input real

Sobre la grabación real, `metrics.py` devolvió `pause_ratio` 0,011,
`mean_utterance_length` 75 y `filler_count` 0.

Ninguno es un defecto de cálculo. Whisper alinea las palabras de forma continua,
así que casi nunca deja huecos mayores al umbral entre el final de una palabra y
el comienzo de la siguiente; y elimina las muletillas al transcribir. Las tres
métricas son correctas y, con esta fuente, inservibles.

Esto corrige la sección 7 del spec de la Fase 1, que daba por buenas esas
métricas sobre timings por palabra.

## 4. Reparaciones de interfaz

### 4.1 La agregación recibe el blueprint

```python
def aggregate(
    blueprint: Sequence[QuestionSlot],
    assessments: Sequence[AnswerAssessment],
) -> ExamResult
```

Hoy `aggregate` solo ve las evaluaciones, y de ahí salen dos carencias: el
informe no puede desglosar por tema ni por tipo de pregunta —que la sección 6
del spec de la Fase 1 exige— y el combo avanzado no influye en la nota pese a
estar construido.

`ExamResult` gana dos desgloses, ambos como tuplas de pares para conservar el
orden y la inmutabilidad:

```python
by_type: tuple[tuple[QuestionType, ActflLevel], ...]
by_topic: tuple[tuple[str, ActflLevel], ...]
```

Cada uno aplica la misma mediana por dimensión que ya usa `dimension_level`,
restringida a las respuestas de ese tipo o ese tema.

**El combo avanzado solo puede subir la nota, nunca bajarla.** Sea `A` la
mediana de todos los niveles de dimensión de las respuestas marcadas
`advanced=True`. Si `A.rank > final.rank`, el nivel final sube un banda, tope en
`A.rank` y en AL. Si `A` queda por debajo, no se aplica penalización: el combo
avanzado existe para sondear el techo del hablante, y fallar por encima del
propio nivel declarado no es evidencia de valer menos.

`aggregate` valida que cada `AnswerAssessment.question_index` corresponda a un
slot del blueprint, y falla con `ValueError` si sobra o falta alguno.

### 4.2 `ExamResult.dimension_levels` deja de ser mutable

Pasa de `dict[Dimension, ActflLevel]` a
`tuple[tuple[Dimension, ActflLevel], ...]`. Hoy es un diccionario dentro de una
dataclass congelada, de modo que `result.dimension_levels[X] = Y` funciona y
altera en silencio un resultado ya puntuado. Un accesor
`level_for(dimension) -> ActflLevel` cubre el uso de lectura.

### 4.3 El Background Survey registra la formación reciente

La parte 2 del survey pregunta, a quien no es estudiante, qué curso tomó por
última vez. Las opciones de la pantalla real son cuatro, y la última es en
realidad una respuesta de antigüedad:

```python
class RecentCourse(Enum):
    DEGREE = "degree"                    # 학위 과정 수업
    PROFESSIONAL = "professional"        # 전문 기술 향상을 위한 평생 학습
    LANGUAGE = "language"                # 어학수업
    OVER_FIVE_YEARS_AGO = "over_5y"      # 수강 후 5년 이상 지남
```

`SurveyAnswers` gana `recent_course: RecentCourse | None`. `validate_survey`
añade una regla: si `is_student` es falso, el campo es obligatorio; si es
verdadero, debe ser `None`. Nuevo miembro `SurveyError.MISSING_COURSE`.

### 4.4 `Question` nace en el núcleo

```python
@dataclass(frozen=True, slots=True)
class Question:
    slot: QuestionSlot
    text_en: str
```

El texto de la pregunta se persiste y aparece en el informe: es un tipo de
dominio. Si lo definiera el adaptador de Ollama, la dependencia quedaría
invertida y `core/` acabaría importando desde la capa de infraestructura para
leer sus propios datos.

## 5. Métricas recalculadas

`core/metrics.py` deja de derivar pausas de los huecos entre palabras y pasa a
usar los tramos de voz que devuelve el VAD.

`Span` y `Transcript` viven en un módulo nuevo, `core/transcript.py`. No van en
`metrics.py` porque los tres puertos los usan y `metrics` es solo uno de sus
consumidores.

```python
@dataclass(frozen=True, slots=True)
class Span:
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    words: tuple[Word, ...]
    speech_spans: tuple[Span, ...]
    duration_s: float


def compute_metrics(transcript: Transcript) -> AnswerMetrics
```

Definiciones, todas deterministas:

- Los tramos separados por menos de `PAUSE_THRESHOLD_S` (0,5 s) se fusionan. Los
  tramos fusionados son los **enunciados**.
- Los huecos entre enunciados son las **pausas**. El silencio anterior al primer
  enunciado y posterior al último no cuenta: es margen de grabación, no
  vacilación.
- `pause_ratio` = tiempo en pausa dividido entre el intervalo que va del inicio
  del primer enunciado al final del último.
- `mean_utterance_length` = número de palabras dividido entre número de
  enunciados.
- `words_per_minute`, `type_token_ratio`, `mean_confidence` y
  `low_confidence_rate` no cambian.

**Muletillas.** Whisper no las transcribe, así que `filler_count` y
`filler_rate` leen cero siempre. Antes de eliminarlas, el plan incluye una tarea
de verificación: sesgar la decodificación con `initial_prompt` hacia
disfluencias suele recuperarlas. Si la prueba sobre el fixture las recupera de
forma fiable, las métricas se quedan y el `initial_prompt` se fija en el
adaptador. Si no, **se eliminan del código junto con `FILLERS`**: un campo que
siempre vale cero miente sobre lo que el sistema mide.

## 6. Capa de adaptadores

Tres protocolos en `core/ports.py`, sin dependencias fuera de la biblioteca
estándar y de `core`:

```python
class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> Path: ...

class SpeechToText(Protocol):
    def transcribe(self, audio: Path) -> Transcript: ...

class Rater(Protocol):
    def rate(
        self,
        question: Question,
        transcript: Transcript,
        metrics: AnswerMetrics,
    ) -> tuple[DimensionScore, ...]: ...
```

Declararlos en `core/` conserva la dirección de dependencia: el motor define lo
que necesita, los adaptadores se adaptan a él, y ninguno de los seis módulos del
núcleo llega a saber que Ollama existe. El test de pureza que ya existe sigue
vigente sin cambios.

Las tres implementaciones viven en `src/opic/adapters/`:

- **`tts.py`** — el `say` de macOS con la voz `Samantha`, convertido a 16 kHz mono
  con `ffmpeg`. La síntesis se cachea en `data/tts_cache/<sha256(texto)>.wav`; una
  pregunta ya sintetizada no se vuelve a generar nunca. Ver 6 bis.
- **`stt.py`** — faster-whisper `medium`, `int8`, con
  `condition_on_previous_text=False`, `temperature=0.0`, `word_timestamps=True`
  y `vad_filter=True`. El VAD es lo que alimenta `speech_spans`.
- **`config.py`** — todos los identificadores y parámetros de modelo en un solo
  sitio (ver sección 7).
- **`llm.py`** — Ollama sobre `http://127.0.0.1:11434`, con el campo `format`
  llevando un esquema JSON que obliga a las cinco dimensiones. El adaptador
  valida que cada cita aparezca literalmente en el transcript y descarta las que
  no; una cita inventada es peor que ninguna evidencia.

## 6 bis. Por qué no Piper

El diseño original fijaba Piper con la voz `en_US-lessac-medium`. Al probarlo,
el paquete `piper-tts` instala correctamente en Python 3.13 sobre ARM pero su
binario de espeak-ng lleva incrustada la ruta de datos de la máquina donde lo
compilaron (`/Users/runner/work/piper1-gpl/...`). Falla en el import, antes de
que ningún código propio pueda intervenir, y no lo redirigen ni la variable
`ESPEAK_DATA_PATH` ni la API interna del paquete. Es un defecto de empaquetado
suyo, no algo que se rodee limpiamente.

> **Corrección, 2026-08-24.** El párrafo anterior describe bien el síntoma y mal
> la causa, y por eso llega a una conclusión equivocada. La ruta compilada está
> ahí, pero no es lo que rompe: espeak-ng guarda el directorio de datos en un
> buffer de **160 caracteres**, trunca lo que no cabe, cae a la ruta compilada
> y mata el proceso al no encontrar `phontab`. Es el issue
> [#272](https://github.com/OHF-Voice/piper1-gpl/issues/272) de piper1-gpl, con
> el PR [#281](https://github.com/OHF-Voice/piper1-gpl/pull/281) sin fusionar.
>
> Medido con `piper-tts 1.7.0` sobre macOS arm64, pasando rutas de longitud
> creciente al mismo `espeak-ng-data`:
>
> | Longitud | Resultado |
> | --- | --- |
> | 67, 101, 131, 151 | Sintetiza: `tˈɛl mˌiːʲ ɐbˌaʊt ðə lˈæst tɹˈɪp juː tˈʊk.` |
> | 161, 171 | Trunca, no encuentra `phontab` y sale |
>
> La prueba original debió correr desde una ruta larga. Piper sirve, en Linux y
> también en macOS, y es lo que usaría un contenedor: allí la ruta ronda los 60
> caracteres. Quien lo instale tiene que mantenerse por debajo de 160 y
> demostrarlo con un test, porque mover el proyecto a un directorio más profundo
> basta para romper la síntesis con un error que señala a otro sitio.
>
> Lo que sigue siendo cierto: `say` no necesita dependencias y ata la
> implementación a macOS, y el puerto `TextToSpeech` hace que cambiarlo sea
> reescribir un archivo.

`say` viene con macOS, sintetiza la frase de prueba en 0,9 segundos, ofrece 43
voces inglesas y funciona sin conexión. A cambio, ata esta implementación a
macOS. El coste es asumible porque todo lo demás también corre en local sobre
esta máquina, y porque el adaptador queda detrás del puerto `TextToSpeech`:
sustituirlo más adelante es reescribir un archivo, sin tocar el núcleo.

## 7. Modelos y configuración

Whisper `medium` queda fijado por 3.1.

Para el evaluador, el plan arranca con **Qwen3 8B con esquema JSON forzado y
salida recortada** —menos evidencia por dimensión, comentarios más breves,
objetivo de unos 250 tokens por respuesta— y contiene una tarea explícita de
comparación contra el 14B sobre el fixture ya versionado. Criterios de la
comparación, decididos antes de mirarla:

1. Las cinco dimensiones presentes, JSON válido, en cinco intentos de cinco.
2. Todas las citas textualmente presentes en el transcript.
3. El coreano, juzgado por el usuario, comparable al del 14B.

Si el 8B cumple los tres, se fija. Si falla cualquiera, se cae al 14B y el
examen se evalúa en unos 22 minutos en vez de unos 12. La decisión se toma con
la medición delante, no antes.

Toda la configuración de modelos vive en un único módulo
`adapters/config.py`, para que cambiar de modelo sea editar un valor y no
buscar por el árbol.

### 7.1 El contrato del detector de voz, que no es negociable

`core/metrics.py` fija `PAUSE_THRESHOLD_S` en 0,5 segundos y calcula pausas y
enunciados a partir de los tramos de voz. Los valores por defecto de
faster-whisper —`min_silence_duration_ms=2000`, `speech_pad_ms=400`— nunca
parten en silencios menores a dos segundos y añaden 0,4 s de relleno a cada
lado. Bajo ellos no puede existir un hueco por debajo de 1,2 s, el umbral de
fusión no dispara jamás, y las métricas vuelven exactamente a los valores
inservibles que motivaron esta fase: se comprobó sobre el fixture y reproducen
`pause_ratio` 0,0112 y `mean_utterance_length` 75,0.

El adaptador **debe** pasar `min_silence_duration_ms≈250` y `speech_pad_ms=0`,
y el plan incluye una tarea que verifica los números resultantes contra
`evidence/sample-transcript.json`. Sin esa verificación, esta fase reabre el
defecto que la fase anterior cerró.

### 7.2 La primera tarea del plan: enlazar la evaluación con su pregunta

La revisión final de la fase anterior dejó esto pendiente por decisión
explícita. Hoy `AnswerAssessment` guarda solo `question_index`, y `ExamResult`
no guarda nada más. Pero la sección 4.4 exige que el texto de la pregunta
aparezca en el informe, y `Evidence.quote` solo es verificable contra la
transcripción de esa respuesta.

Sin el enlace, la capa de informe arrastra diccionarios paralelos junto a un
resultado que se declara inmutable. `AnswerAssessment` gana `question: Question`
y `transcript: Transcript`, y esa es la tarea que abre el plan — antes de los
puertos, porque los puertos se declaran sobre estos tipos.

## 7 bis. La fase se implementa en dos planes

El alcance no entra en un solo plan de implementación, y las dos mitades tienen
requisitos distintos: la primera no necesita ningún modelo descargado, la segunda
no puede probarse sin ellos.

**Plan A — reparaciones del núcleo.** Secciones 4 y 5: los cuatro cambios de
interfaz, `core/transcript.py`, y las métricas recalculadas sobre `speech_spans`.
Toca los seis módulos existentes y su batería de tests. Al terminar, el núcleo
sigue siendo puro y sigue corriendo en menos de un segundo.

**Plan B — adaptadores y recorrido completo.** Secciones 6 y 7: los tres puertos,
sus implementaciones, la comparación 8B contra 14B, la verificación del
`initial_prompt`, y el examen entero por línea de comandos.

Plan A se escribe y se ejecuta primero. Plan B se escribe cuando A haya caído,
porque el resultado de la verificación de muletillas cambia lo que B implementa.

## 8. Pruebas

El núcleo mantiene su batería actual, rápida y sin modelos.

Los adaptadores se prueban en dos niveles:

- **Contra el fixture**, sin cargar modelo alguno: la transcripción real ya
  versionada alimenta `compute_metrics` y el `Rater`, de modo que las métricas y
  el parseo de la respuesta del LLM se verifican contra habla real en vez de
  contra datos inventados.
- **Contra los modelos reales**, bajo la marca `@pytest.mark.models`, excluida
  por defecto. Son lentas y requieren Ollama levantado; se ejecutan a mano
  cuando se cambia de modelo o de configuración.

El recorrido completo de examen por línea de comandos es la prueba de
aceptación de la fase.

## 9. Riesgos

**El 8B no alcanza.** Mitigación: el criterio de decisión está escrito arriba y
el fallback al 14B es un cambio de una línea en `adapters/config.py`.

**El `initial_prompt` no recupera las muletillas.** Entonces se borran las dos
métricas. Está previsto, no es un imprevisto.

**`say` ata la implementación a macOS.** Asumido a sabiendas en 6 bis. El puerto
`TextToSpeech` es la frontera que mantiene barato el cambio.

**El VAD segmenta de forma distinta a como percibe un evaluador humano.** Los
tramos de Silero se ajustan a energía, no a sintaxis. Mitigación: la fusión por
umbral de 0,5 s y la validación de los números resultantes contra el fixture,
donde ya sabemos cómo suena la grabación.

**El tiempo de evaluación sigue siendo largo.** Incluso en el mejor caso son
unos 25 minutos por examen entre transcripción y juicio. La Fase 3 debe diseñar
la espera como un trabajo en segundo plano al que se vuelve, no como un
indicador de progreso que se mira.

## 10. Criterios de éxito

- Un examen completo se ejecuta por línea de comandos: survey, blueprint,
  síntesis de las quince preguntas, grabaciones de entrada, transcripción,
  evaluación e informe.
- El informe cita fragmentos que aparecen literalmente en lo que se dijo.
- Repetir la evaluación sobre los mismos audios da el mismo nivel.
- Los tests del núcleo siguen corriendo en menos de un segundo sin modelos.
- El equipo puede estar desconectado de internet.
