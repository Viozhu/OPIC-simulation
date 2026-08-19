# Simulador OPIc con IA local — Diseño

Fecha: 2026-08-19
Estado: aprobado, pendiente de plan de implementación

## 1. Objetivo

Una aplicación web que corre entera en la máquina local y simula el examen
OPIc de expresión oral en inglés. El usuario atraviesa el mismo recorrido que
en el examen real —Background Survey, Self Assessment, Setup, Sample Question
y el test— hablando por micrófono. Al terminar recibe un nivel ACTFL, un
desglose por dimensiones y las citas textuales de sus errores.

Público objetivo: hablantes de coreano que preparan el OPIc. La interfaz va en
coreano; el examen y las respuestas, en inglés.

Todo el procesamiento de IA ocurre en el equipo. Ningún audio ni transcripción
sale de la máquina.

## 2. Alcance

Dentro:

- Los cinco pasos del examen, fieles al original.
- Reproducción de las preguntas en audio y grabación de las respuestas.
- Transcripción y evaluación automáticas al terminar.
- Informe con nivel ACTFL, sub-scores y evidencia citada.
- Persistencia local de sesiones, audios y resultados.

Fuera, por ahora:

- Modo de práctica corta (drill). El esquema de datos lo permitirá después.
- Seguimiento de progreso entre sesiones y gráficas de tendencia.
- Respuestas modelo reescritas al nivel objetivo.
- Cualquier proveedor de IA remoto.
- Autenticación y multiusuario. Un solo usuario, una sola máquina.

## 3. Decisiones tomadas

| Decisión | Elección | Razón |
|---|---|---|
| Modalidad | Voz completa: TTS para preguntas, STT para respuestas | Es lo que mide el OPIc |
| Alcance del examen | Completo y fiel, con role-play | Máximo realismo |
| Salida del score | Nivel ACTFL + desglose + evidencia citada | El desglose es lo que enseña |
| Interfaz | Web local: FastAPI sirviendo HTML y JS sin build | Micro y audio nativos del navegador, un solo proceso |
| Runtime de IA | Ollama + faster-whisper + Piper | Gratis, offline, fácil de cambiar de modelo |
| Idioma | Interfaz en coreano, examen en inglés | El público objetivo es coreano |
| Momento de evaluar | Diferido, al terminar el examen | La latencia local no debe romper el ritmo |

Ollama, los modelos, Whisper y Piper son gratuitos y de código abierto. El
único coste es disco, memoria y batería.

## 4. Arquitectura

Un proceso Python. FastAPI sirve la interfaz y expone una API REST más un
WebSocket para el progreso de la evaluación. El estado vive en SQLite y los
audios en disco.

La regla estructural que gobierna el proyecto: **`core/` no importa FastAPI ni
ningún cliente de IA**. El motor —survey, generación de preguntas, rúbrica,
métricas, agregación del score— es Python puro. Los modelos se alcanzan a
través de adaptadores con una interfaz estrecha, sustituibles por dobles en los
tests.

Consecuencia práctica: la batería de tests del motor corre en milisegundos sin
Ollama ni Whisper cargados. Solo un puñado de tests de integración toca los
modelos reales.

## 5. Flujo del examen

Derivado de capturas de una simulación real (`evidence/`).

### Step 1 — Background Survey, cuatro partes

1. Ocupación: empresa / teletrabajo o negocio propio / docente / sin
   experiencia laboral.
2. ¿Estudiante? Sí o no. Si no: qué formación cursó por última vez y hace
   cuánto tiempo.
3. Vivienda: solo / con amigos o compañeros / con familia / residencia
   estudiantil / cuartel militar.
4. Intereses. **Mínimo doce ítems en total**, repartidos en cuatro grupos: ocio
   (dos o más), aficiones (uno o más), deporte (uno o más), viajes (uno o más).
   Contador en vivo, igual que el original.

La parte 4 es una palanca estratégica del examen real: elegir un solo ítem de
un grupo hace que salga una sola pregunta de ese grupo. El simulador respeta
esa mecánica —las preguntas salen únicamente de lo marcado— porque practicar
esa estrategia forma parte de prepararse.

### Step 2 — Self Assessment

Seis niveles descritos, cada uno con audio de muestra. La elección del usuario
fija la dificultad del set de preguntas.

### Step 3 — Setup

Prueba de micrófono: grabar, reproducir, confirmar que se oye.

### Step 4 — Sample Question

Una pregunta de ejemplo que no puntúa.

### Step 5 — Test

Entre doce y quince preguntas, organizadas en combos de tres sobre un mismo
tema:

1. Descripción: describe tu X.
2. Hábito: qué haces normalmente con X.
3. Experiencia: algo que te ocurrió relacionado con X.

Más un role-play y un combo de dificultad superior a la autoevaluada.

## 6. Generación de preguntas

Entrada: los temas marcados en el survey y el nivel del self assessment.
Salida: el set completo de preguntas, generado **antes** de empezar el examen.

Generar por adelantado tiene dos efectos deseables: el examen corre sin esperar
nunca al LLM, y el audio de cada pregunta puede sintetizarse y cachearse
mientras el usuario todavía está en el Setup.

Cada pregunta se persiste con su tema y su tipo (descripción, hábito,
experiencia, role-play), porque el informe final agrupa el rendimiento por esas
categorías.

## 7. Pipeline de voz

Durante el examen no interviene ningún LLM:

    pregunta (texto en inglés) → Piper → audio
                                   ↓ se reproduce
                        el usuario habla (MediaRecorder)
                                   ↓ webm/opus
                        se guarda a disco → siguiente pregunta

El TTS se cachea por hash del texto: una pregunta repetida no se vuelve a
sintetizar nunca.

Al terminar, con una pantalla de progreso (채점 중):

    audios → faster-whisper con timestamps por palabra → transcripción
                │
                ├→ métricas objetivas, calculadas en Python:
                │    palabras por minuto, ratio de pausa, muletillas,
                │    type-token ratio, longitud media de enunciado
                │
                └→ Qwen3: transcripción + métricas + rúbrica ACTFL
                          → sub-scores y citas por respuesta
                          → agregación → nivel final

## 8. Scoring

Las métricas objetivas se calculan en código, no se le piden al modelo. Un LLM
local inventa cifras; contar palabras por minuto es aritmética. El modelo juzga
únicamente lo que sabe juzgar: gramática, coherencia, riqueza léxica y si la
respuesta contesta lo que se preguntó. Esto hace el resultado reproducible y
auditable.

Dimensiones del informe: fluidez, gramática, vocabulario, coherencia y
desarrollo del discurso, y adecuación a la pregunta.

Pronunciación: Whisper no la mide de forma fiable. Se reporta un proxy honesto
—confianza media de transcripción y tasa de palabras dudosas— **etiquetado como
indicativo, no como nota**. El informe lo declara explícitamente.

Nivel final: la escala ACTFL usada por el OPIc, en este orden: NL, NM, NH, IL,
IM1, IM2, IM3, IH y AL. La agregación es una regla determinista sobre los sub-scores,
definida en `rubric.py`, no una opinión libre del modelo.

El informe advierte que el nivel es consistente y útil para medir progreso,
pero no es oficial ni predice la nota real.

## 9. Datos

SQLite, un fichero local:

    session ── survey_answer
            ── question ── answer (ruta de audio, transcripción, métricas)
                        ── score  (dimensiones, nivel, evidencia)

Los audios crudos viven en `data/sessions/<id>/`. El caché de TTS, en
`data/tts_cache/`.

Este esquema ya soporta el histórico de progreso, aunque la primera versión no
lo explote.

## 10. Estructura de ficheros

    opic-test/
    ├─ pyproject.toml            uv
    ├─ src/opic/
    │  ├─ core/                  motor puro, sin dependencias de web ni IA
    │  │   survey.py             schema del Background Survey (ko/en)
    │  │   selfassess.py         los seis niveles y las reglas de dificultad
    │  │   questions.py          construcción del set de preguntas
    │  │   rubric.py             escala ACTFL y criterios de agregación
    │  │   metrics.py            WPM, pausas, muletillas, TTR
    │  │   scoring.py            agregación al nivel final
    │  ├─ adapters/              puertos sustituibles por dobles
    │  │   llm.py                Ollama
    │  │   stt.py                faster-whisper
    │  │   tts.py                Piper, con caché por hash
    │  ├─ web/
    │  │   app.py                FastAPI: REST y WebSocket de progreso
    │  │   static/ templates/
    │  └─ store/db.py            SQLite
    ├─ data/sessions/<id>/
    ├─ data/tts_cache/
    ├─ evidence/                 capturas de referencia del examen real
    ├─ docs/superpowers/specs/
    └─ tests/

## 11. Stack

- Python 3.13, gestionado con uv.
- FastAPI y Uvicorn.
- Ollama con Qwen3 14B cuantizado, elegido por su solvencia en coreano.
- faster-whisper, tamaño small o medium según la calidad observada.
- Piper, voz inglesa para las preguntas.
- Interfaz: HTML y JavaScript sin paso de build.

Hardware de referencia: Apple M2, 24 GB de RAM, macOS 26.5. Suficiente para
sostener los tres modelos a la vez.

Ollama no está instalado todavía; instalarlo es el primer paso de la fase 2.

## 12. Orden de construcción

Cada fase deja algo verificable:

1. `core/` con sus tests: survey, generación de preguntas, rúbrica, métricas y
   agregación, contra transcripciones de ejemplo fijas.
2. Adaptadores reales. Verificar que Qwen3 redacta coreano aceptable y que
   Whisper no corrige la gramática del hablante.
3. Interfaz web: los cinco pasos, grabación de micrófono y reproducción del TTS.
4. Pipeline de evaluación diferida con pantalla de progreso.
5. Informe de score.

## 13. Riesgos

**Whisper transcribe demasiado bien.** Sus modelos tienden a corregir la
gramática del hablante al vuelo, lo que borraría justo los errores que
queremos evaluar. Mitigación: `condition_on_previous_text=False`, temperatura
cero, y verificación manual en la fase 2 contra una grabación con errores
deliberados. Si la corrección persiste, bajar el tamaño del modelo o evaluar
alternativas.

**El nivel ACTFL no es oficial.** Un modelo local es consistente consigo mismo
pero no está calibrado contra evaluadores humanos certificados. Se comunica en
el informe.

**La pronunciación no se mide de verdad.** Ya tratado en la sección 8: proxy
declarado como indicativo.

**Calidad del coreano del LLM.** Si Qwen3 14B no rinde, la alternativa es un
modelo específico de coreano o generar el informe en inglés con los términos
clave traducidos. Se decide con la prueba de la fase 2, no antes.

## 14. Criterios de éxito

- Un examen completo se puede realizar de principio a fin sin intervención
  manual ni esperas perceptibles entre preguntas.
- El informe cita fragmentos reales de lo que el usuario dijo.
- Repetir la evaluación sobre los mismos audios produce el mismo nivel.
- Todo funciona con el equipo desconectado de internet.
