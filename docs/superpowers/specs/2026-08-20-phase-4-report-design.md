# Fase 4 — El informe

Fecha: 2026-08-20
Estado: aprobado, pendiente de plan de implementación

Continúa `2026-08-19-opic-simulator-design.md` (diseño maestro) y
`2026-08-19-phase-3-web-design.md`, que dejó explícitamente fuera «el informe
presentable, con desglose por dimensiones, citas y proxy de pronunciación».
Esto es esa fase.

## 1. Objetivo

Que el candidato entienda **por qué** sacó el nivel que sacó, y qué hacer al
respecto. Hoy el pipeline calcula el desglose por dimensión, los comentarios
en coreano del modelo, las citas de sus propios errores y las métricas de
habla — y la pantalla de resultado enseña el nivel final y poco más.

## 2. Alcance

Dentro:

- Informe legible en coreano en el navegador: encabezado, desglose por
  dimensión con comentario y citas, palabras no reconocidas con claridad,
  desglose por tipo y tema, y detalle respuesta por respuesta.
- El mismo informe en texto para la CLI.
- Un modelo de vista construido en Python, servido como JSON.
- Etiquetas coreanas para los tipos de pregunta.
- Explicación del tope por dimensión débil cuando se aplica.

Fuera:

- Cambiar cómo se puntúa. `aggregate` y la rúbrica no se tocan salvo por un
  helper público de solo lectura (§6).
- Gráficas, PDF, exportación, comparación entre sesiones. No hay histórico.
- Validar que el modelo respondió en coreano. Se pinta lo que haya (§9).
- Tests de JavaScript. La decisión de fondo es que JS no decida nada (§8).

## 3. Decisiones tomadas

| Decisión | Elección | Razón |
|---|---|---|
| Profundidad | Agregado + detalle por respuesta | `result.json["answers"]` ya trae transcript, métricas y citas de las 15 |
| Dónde se renderiza | Python arma el modelo, JS pinta | Todo el suite es Python; `done.js` no tiene ni un test |
| Proxy de pronunciación | Las palabras concretas bajo el umbral, no una nota | El docstring de `PronunciationProxy` dice «never a band»; los umbrales serían inventados |
| Métricas | Cinco campos, contra la media del propio examen | Un `94.5 wpm` suelto no es interpretable; contra uno mismo sí |
| `type_token_ratio` | No se muestra | Depende de la longitud; comparar respuestas desiguales engaña |
| Ruta | `/api/sessions/{id}/report` nueva | `/result` sigue crudo e intacto; los tests de fase 3 no se editan |
| Origen de los datos | Reconstruido desde `answer-NN.json` | Funciona con sesiones ya calificadas; sin fichero nuevo ni migración |
| Etiquetas de tema | Reusar `label_ko` de `core/survey.py` | Ya existen; no se inventa una tabla paralela |

## 4. Lo que ya existe y no se enseña

Medido sobre el código, no sobre el recuerdo:

- `DimensionScore.comment_ko` — comentario del modelo por dimensión.
- `Evidence(quote, issue_ko, correction_en)` — la cita literal del candidato,
  qué falla en coreano, y la corrección en inglés. `parse_rating`
  (`adapters/llm.py:124`) ya descarta toda cita que no aparezca literal en el
  transcript, así que una cita mostrada es siempre real.
- `ExamResult.by_type` y `ExamResult.by_topic`.
- `PronunciationProxy.mean_confidence` y `.low_confidence_rate`.
- Por respuesta: transcript completo, `Word.probability` por palabra, y las
  ocho métricas de `AnswerMetrics`.

`GET /api/sessions/{id}/result` (`web/app.py:343`) ya devuelve todo eso
verbatim. `done.js` pinta el nivel final, el contador de respuestas, la lista
`dimensión: nivel`, y esconde el resto en un `<details>` de JSON crudo.

Observación que motiva la fase: el aviso que ya se muestra dice
`발음 지표는 참고용입니다` — promete un indicador de pronunciación que la
pantalla nunca enseña.

## 5. Arquitectura

```
answer-NN.json ──read_all_answers──> AnswerAssessment[]
                                          │
                          aggregate_available (existente)
                                          │
                                     ExamResult
                                          │
                                   build_report  ← core/report.py (nuevo)
                                          │
                                       Report
                                    ┌─────┴─────┐
                            report_json     render_text
                                 │               │
                        GET /report → done.js   cli.py
```

Un solo sitio decide qué se enseña. El navegador y la terminal ven lo mismo.

### 5.1 `src/opic/core/report.py` (nuevo, puro)

El guard de pureza (`tests/test_core_purity.py`) solo prohíbe importar
infraestructura; formatear texto es legal en `core`.

Dataclasses congeladas:

- `Report` — `final_level`, `scored_answers`, `expected_answers`,
  `limiting: LimitingDimension | None`, `dimensions: tuple[DimensionSummary, ...]`,
  `unclear: tuple[UnclearWord, ...]`, `by_type`, `by_topic`,
  `averages: MetricSummary | None`, `answers: tuple[AnswerReport, ...]`.
- `DimensionSummary` (nivel examen) — `dimension`, `label_ko`, `weight`,
  `level`, `evidence: tuple[EvidenceRef, ...]`.
- `DimensionDetail` (nivel respuesta) — `dimension`, `label_ko`, `level`,
  `comment_ko`, `evidence: tuple[Evidence, ...]`.
- `EvidenceRef` — `quote`, `issue_ko`, `correction_en`, `answer_index`.
- `AnswerReport` — `index`, `question_en`, `qtype_label_ko`, `topic_label_ko`,
  `state` (`scored` | `not_scored` | `unreadable`), `transcript_text`,
  `metrics: MetricSummary | None`, `scores: tuple[DimensionDetail, ...]`.
- `UnclearWord` — `text`, `probability`, `context`, `answer_index`.
- `MetricSummary` — `duration_s`, `word_count`, `words_per_minute`,
  `pause_ratio`, `mean_utterance_length`.
- `LimitingDimension` — `dimension`, `label_ko`, `level`, `without_cap: ActflLevel`.

**Por qué dos tipos de dimensión.** `ExamResult.dimension_levels` es solo
`(Dimension, ActflLevel)`: los comentarios y las citas viven por respuesta, no
por examen. Un `comment_ko` a nivel de examen no existe — habría que elegir uno
de quince o inventar un resumen, y ninguna de las dos cosas es un dato. Así que
la sección de examen muestra nivel y las citas recogidas de todas las
respuestas, cada una etiquetada con la pregunta de la que salió
(`EvidenceRef.answer_index`); los comentarios se leen en el detalle por
respuesta.

Funciones:

- `build_report(result: ExamResult, questions: Sequence[Question], unreadable: Sequence[int] = ()) -> Report`
- `render_text(report: Report) -> str`

`questions` es la lista completa del examen, no solo las puntuadas: es lo que
permite nombrar en §7.5 las respuestas que faltan. `expected_answers` sale de
su longitud. `unreadable` son los índices cuyo `answer-NN.json` no se pudo leer
(§9). La ruta convierte `QuestionRecord` en `Question` con el
`question_from_record` que ya existe, así que `core` no ve la capa de sesión.

### 5.2 Serialización

`report_json(report) -> dict` vive en `session/assessments.py`, al lado de
`result_json`. `core` no serializa: es la frontera que ya respeta el resto del
proyecto.

### 5.3 Ruta

```
GET /api/sessions/{session_id}/report
```

- 404 si no existe `result.json`, con el mismo mensaje que `/result` — que
  exista el resultado es lo que marca que el examen terminó.
- Carga `session.json`, lee las respuestas con `read_all_answers`, agrega con
  `aggregate_available` (no con `aggregate`: exige coincidencia exacta con el
  blueprint y reventaría con una respuesta fallida), construye el `Report` y lo
  devuelve.
- `/result` no cambia. `done.js` lo sigue usando para el `<details>` crudo.

Coste: quince lecturas de JSON, ninguna llamada a modelo. No se persiste nada
nuevo, así que toda sesión ya calificada obtiene su informe sin migración.

## 6. El tope por dimensión débil

`aggregate` aplica `_capped`: si alguna dimensión queda `WEAK_DIMENSION_GAP`
(3) bandas o más por debajo del rango calculado, el resultado baja una banda
(`core/scoring.py:113-120`). `ExamResult` no guarda que eso pasó.

Es la respuesta a «por qué no subo», así que el informe lo dice. **Corrección
sobre lo que se habló en la conversación: no sale gratis.** El rango previo al
tope incluye la subida por combo avanzado, que no es derivable de
`ExamResult.dimension_levels`; hace falta el conjunto de assessments y sus
slots. Reconstruirlo desde `report.py` obligaría a importar `_weighted_rank` y
`_capped`, privados de otro módulo.

Por tanto `core/scoring.py` gana una función pública, en el módulo que ya es
dueño de la regla:

```python
def limiting_dimension(
    blueprint: Sequence[QuestionSlot],
    assessments: Sequence[AnswerAssessment],
) -> tuple[Dimension, ActflLevel] | None:
    """La dimensión que hizo bajar una banda, y el nivel sin ese tope."""
```

Devuelve `None` si el tope no se aplicó. No cambia ningún resultado: es
solo-lectura y reusa los helpers existentes. `build_report` la llama y llena
`Report.limiting`.

## 7. El informe, sección por sección

Títulos en coreano, en este orden.

**7.1 최종 등급.** Nivel final. Debajo, `15개 중 N개의 답변으로 산출되었습니다`,
marcado si `N < expected`. Y el aviso de que no es una puntuación oficial.

**7.2 왜 이 등급인가.** Las cinco dimensiones en orden de peso descendente
(유창성 25%, 문법 20%, 어휘 20%, 구성력 20%, 질문 적합성 15%), cada una con su
nivel y las citas que esa dimensión acumuló a lo largo del examen, cada una
diciendo de qué pregunta salió. Los `comment_ko` no se agregan aquí (§5.1): se
leen en §7.5, junto a la respuesta que los provocó.

**Cuántas citas.** No todas. Medido sobre el examen real del 2026-08-20:
73 evidencias repartidas en 71 puntuaciones de dimensión, o sea unas quince por
dimensión. Volcarlas en la pantalla principal no es un informe, es el JSON con
otra tipografía. `build_report` acota a `EXAM_EVIDENCE_PER_DIMENSION = 3`,
prefiriendo citas de preguntas distintas para no gastar las tres en la misma
respuesta. No se esconde nada: §7.5 sigue llevando todas las citas de cada
respuesta. El límite vive en `core` para que la terminal y el navegador hereden
el mismo, y para que sea testeable.

El prompt pide como mucho una evidencia por dimensión (`llm.py:244`) pero
`RATING_SCHEMA` no lo obliga, y en el examen real del 2026-08-20 la primera
respuesta trajo dos en 유창성. El informe renderiza N, no asume una.

Cada cita: el `quote` en inglés tal cual lo dijo, el `issue_ko` en coreano, y
`correction_en` en inglés. La corrección se queda en inglés a propósito: es la
frase que tiene que aprender a decir. El marco alrededor va en coreano.

Si `Report.limiting` no es `None`, una línea: el nivel final está limitado por
esa dimensión, y cuál habría sido sin el tope.

**7.3 또렷하게 인식되지 않은 단어.** Las palabras con
`probability < LOW_CONFIDENCE_THRESHOLD` (0.6, `core/metrics.py`), cada una con
su contexto y de qué respuesta viene.

El contexto son las cinco palabras anteriores y las cinco siguientes del propio
flujo de palabras, no «la frase»: `Transcript` guarda palabras con tiempos, no
oraciones, y partir `transcript.text` por puntuación para volver a casarlo con
`Word` es frágil y falla justo donde el reconocedor dudó. Una ventana fija es
determinista y testeable.

El encabezado dice lo que el dato es: el reconocedor no las captó con claridad.
Es una afirmación sobre el reconocedor, no sobre la boca del candidato — y es
lo único accionable, porque puede ir y repetirlas. `mean_confidence` y
`low_confidence_rate` **no se muestran como número**: esta sección es el proxy.

Si no hay ninguna, la sección dice que se entendió todo. No una lista vacía.

**7.4 유형별 · 주제별.** `by_type` con la tabla nueva de §7.6, `by_topic` con
los `label_ko` que ya tiene `core/survey.py`. Vale por lo comparativo: 묘사 se
te da mejor que 롤플레이. Si `by_topic` viene vacío, la sección no se dibuja.

**7.5 답변별 상세.** Las quince, en orden. Cada una: la pregunta en inglés, su
tipo y tema, el transcript, sus notas por dimensión con citas, y las métricas
de §7.7 junto a la media del examen.

Una respuesta no puntuada aparece igual, marcada 채점하지 못한 답변. No
desaparece en silencio.

**7.6 Etiquetas de tipo de pregunta.** Tabla nueva `QUESTION_TYPE_LABELS_KO` en
`core/rubric.py`, junto a `DIMENSION_LABELS_KO` — mismo patrón, mismo sitio:

| `QuestionType` | Etiqueta |
|---|---|
| `SELF_INTRO` | 자기소개 |
| `DESCRIPTION` | 묘사 |
| `HABIT` | 습관·일상 |
| `EXPERIENCE` | 경험 |
| `ROLEPLAY_SETUP` | 롤플레이 (상황 설정) |
| `ROLEPLAY_FOLLOWUP` | 롤플레이 (후속) |

Los temas no necesitan tabla: `core/survey.py` ya tiene `label_ko` por ítem.

**7.7 Métricas mostradas.** Cinco de las ocho, cada una contra la media de las
respuestas puntuadas de este mismo examen:

| Campo | Etiqueta |
|---|---|
| `duration_s` | 답변 길이 |
| `word_count` | 단어 수 |
| `words_per_minute` | 말하기 속도 |
| `pause_ratio` | 침묵 비율 |
| `mean_utterance_length` | 평균 발화 길이 |

`type_token_ratio` no se muestra: varía con la longitud de la respuesta y
comparar respuestas desiguales induce a conclusiones falsas.
`mean_confidence` y `low_confidence_rate` tampoco: son §7.3.

La referencia es el propio examen porque no hay datos calibrados para umbrales
absolutos. Un número contra la media propia es comparable; contra un umbral
inventado, no.

## 8. `done.js` y la CLI

`done.js` pide `/report`, itera y pinta. No decide etiquetas, ni orden, ni
cómo presentar nada. Conserva el `<details>` de JSON crudo contra `/result`.

Que JS no tenga tests es la consecuencia buscada, no un olvido: si no decide
nada, no hay lógica que testear, y no se introduce un runner de JavaScript en
un repo cuyo suite entero es pytest.

`cli.py` sustituye sus dos `print` (`cli.py:249-250`) por `render_text`. Sigue
imprimiendo la ruta de `result.json` al final.

## 9. Cuando algo falla

- **Sin `result.json`** → 404, igual que `/result`.
- **Menos respuestas puntuadas que preguntas.** `read_all_answers` va por
  `state.scored_indices()`, así que una fallida no está. El encabezado lo
  cuenta y §7.5 la nombra.
- **`answer-NN.json` ilegible.** Hoy `read_answer` propaga el `JSONDecodeError`
  y la ruta daría un 500 sobre un examen completado. El informe salta esa
  respuesta, la marca `unreadable` en §7.5 y sigue. Un fichero roto no puede
  costar las otras catorce. El agregado se calcula sobre las que sí se
  leyeron.
- **Ninguna respuesta legible** → 404 con el mismo mensaje que «aún no
  calificado». No se inventa un informe vacío.
- **`comment_ko` vacío, o el modelo respondiendo en inglés** → se pinta lo que
  haya. Validar el idioma del modelo es otra fase; rellenar el hueco con texto
  inventado sería peor que el hueco.
- **Cita cuyo `quote` no está en el transcript** → imposible por construcción,
  `parse_rating` ya las descarta.

## 10. Verificación

- `tests/core/test_report.py` — `build_report` en puro: orden por peso, N
  evidencias por dimensión, extracción de palabras poco claras con su frase,
  medias, respuesta ausente vs. ilegible, y el caso sin palabras poco claras.
- `tests/core/test_scoring.py` — se amplía con `limiting_dimension`: aplica,
  no aplica, y el nivel sin tope.
- `tests/web/test_report_route.py` — 404 antes de tiempo, forma del JSON,
  informe parcial con una respuesta fallida, y que `/result` sigue devolviendo
  exactamente lo de antes.
- `tests/test_cli.py` — `render_text` imprime el desglose, no solo el nivel.
- **Fixture con datos reales.** El `result.json` y los `answer-NN.json` del run
  de aceptación del 2026-08-20 se copian a `evidence/`. Mismo criterio que
  `sample-transcript.json`: pruebas contra salida real del modelo, no contra
  datos inventados. Incluye el caso de las dos evidencias en una dimensión,
  que un fixture escrito a mano no habría tenido.

## 11. Riesgos

- **El texto del modelo manda en la legibilidad.** `comment_ko` e `issue_ko`
  son coreano libre generado por qwen3:14b; el informe no puede mejorarlos.
  Si salen malos, el informe sale malo. Se sabrá al leer el del run real.
- **La lista de palabras poco claras puede crecer.** 0.07 sobre 71 palabras
  fueron unas cinco; una respuesta larga y mal reconocida podría dar treinta.
  Si el run real lo muestra, se acota por respuesta en el plan.
- **`limiting_dimension` duplica la regla si `_capped` cambia.** Vive en el
  mismo módulo y reusa los mismos helpers precisamente para que no se
  desincronice, pero es un sitio más que tocar si la regla se mueve.

## 12. Criterios de éxito

1. Terminado un examen, la pantalla de resultado explica el nivel: qué
   dimensión falló, con qué frase suya, y qué debió decir.
2. El mismo informe sale por la CLI.
3. Un examen con respuestas fallidas o un fichero corrupto produce informe
   igual, diciendo qué falta.
4. Ninguna cifra mostrada carece de referencia interpretable.
5. `pytest` verde, incluidos los tests de fase 3 sin editar.
