# Multi-sesión, despliegue permanente y feedback — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que varios invitados puedan examinarse a lo largo del tiempo desde un
enlace permanente, que cada examen lleve nombre y correo, y que al terminar el
candidato deje una valoración que aterrice en una hoja de Google.

**Architecture:** Tres bloques sobre el código que ya existe. Primero el
esquema: `session.json` gana `created_at`, `candidate` y `feedback`, y el id de
sesión pasa a ser un token aleatorio. Después el feedback: un puerto `SheetSink`
nuevo en `core/ports.py`, un adaptador sobre un webhook de Apps Script, y una
tarea `publish` en el worker que ya existe. Por último el despliegue: túnel
Cloudflare con nombre, dos agentes de `launchd`, `/healthz` y las barandillas
que estar en pie 24/7 vuelve obligatorias. No se toca la cola: sigue habiendo un
worker y un examen a la vez.

**Tech Stack:** Python 3.13, FastAPI, pytest, `uv`. Sin dependencias nuevas: el
adaptador de la hoja usa `urllib.request` de la biblioteca estándar. Frontend en
JavaScript de módulos ES, sin framework ni herramienta de compilación.

**Spec:** `docs/superpowers/specs/2026-08-31-multi-sesion-y-despliegue-design.md`

## Global Constraints

- **Rama:** `multi-session`. El árbol de trabajo está en
  `.claude/worktrees/multi-session`.
- **Sin dependencias nuevas.** `pyproject.toml` no cambia. Si una tarea parece
  pedir un paquete, está mal planteada.
- **Todo lo que ve el candidato va en coreano.** Los mensajes de error de la API
  llevan `message_ko`, igual que `put_survey` y `put_level` hacen hoy.
- **Ninguna prueba toca la red ni una hoja real.** El adaptador se prueba con un
  `opener` falso inyectado.
- **Las catorce sesiones de `data/sessions` deben seguir cargando** después de
  cada tarea. No se renombra ninguna carpeta.
- **Pruebas:** `uv run pytest` (excluye por defecto las marcadas `models`).
  Lint: `uv run ruff check src tests`.
- **Un examen a la vez.** Ninguna tarea cambia el worker único ni la cola.
- Nombres de variables de entorno, exactos: `OPIC_SHARE_TOKEN` (ya existe),
  `OPIC_SHEET_URL`, `OPIC_PUBLIC_URL`.

---

### Task 1: Ids no adivinables y `created_at`

Cierra §5 del diseño. Va primero porque cambia la forma de `session.json` y todo
lo demás escribe encima.

**Files:**
- Modify: `src/opic/session/state.py` (`SessionState`, `SessionState.new`)
- Modify: `src/opic/session/store.py` (`new_session_id`, `create`, `load`,
  `to_json`, `from_json`, `list_unfinished`)
- Test: `tests/session/test_store.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `store.new_session_id() -> str` — **sin argumentos** (antes recibía `now`).
  - `store.create(root: Path, seed: int, now: datetime) -> SessionState` — la
    firma no cambia; `now` pasa a alimentar `created_at`.
  - `SessionState.created_at: datetime` — campo nuevo, obligatorio.
  - `SessionState.new(session_id: str, seed: int, created_at: datetime)`.
  - `store.from_json(payload: dict, fallback: datetime | None = None) -> SessionState`.
  - `store.list_unfinished(root: Path) -> tuple[str, ...]` — ahora ordenado por
    `created_at`, no por nombre de carpeta.

- [ ] **Step 1: Escribir las pruebas que fallan**

En `tests/session/test_store.py`, **sustituir** `test_the_id_is_the_creation_timestamp`
(que afirma lo contrario de lo que queremos) por estas, y añadir el resto:

```python
def test_the_id_is_not_guessable():
    first = store.new_session_id()
    second = store.new_session_id()
    assert first != second
    assert len(first) >= 22
    assert "-" not in first or not first[:8].isdigit()


def test_create_records_when_it_happened(tmp_path: Path):
    made = datetime(2026, 8, 31, 14, 30, 52)
    state = store.create(tmp_path, seed=7, now=made)
    assert state.created_at == made
    assert store.load(tmp_path, state.id).created_at == made


def test_two_sessions_in_the_same_second_do_not_share_a_folder(tmp_path: Path):
    same = datetime(2026, 8, 31, 14, 30, 52)
    first = store.create(tmp_path, seed=1, now=same)
    second = store.create(tmp_path, seed=2, now=same)
    assert first.id != second.id
    assert store.load(tmp_path, first.id).seed == 1
    assert store.load(tmp_path, second.id).seed == 2


def test_a_legacy_session_takes_its_date_from_its_folder_name(tmp_path: Path):
    directory = tmp_path / "20260819-143052"
    directory.mkdir(parents=True)
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 31, 14, 0, 0))
    payload = json.loads((tmp_path / state.id / "session.json").read_text(encoding="utf-8"))
    del payload["created_at"]
    payload["id"] = "20260819-143052"
    (directory / "session.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert store.load(tmp_path, "20260819-143052").created_at == datetime(2026, 8, 19, 14, 30, 52)


def test_unfinished_sessions_come_back_oldest_first(tmp_path: Path):
    late = store.create(tmp_path, seed=1, now=datetime(2026, 8, 31, 18, 0, 0))
    early = store.create(tmp_path, seed=2, now=datetime(2026, 8, 31, 9, 0, 0))
    assert store.list_unfinished(tmp_path) == (early.id, late.id)
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `uv run pytest tests/session/test_store.py -v`
Expected: FAIL — `new_session_id() takes 1 positional argument but 0 were given`,
y `SessionState` sin `created_at`.

- [ ] **Step 3: `created_at` en el estado**

En `src/opic/session/state.py`, añadir el import y el campo:

```python
from datetime import datetime
```

En `SessionState`, tras `id: str`:

```python
    created_at: datetime
```

Y `new` pasa a:

```python
    @classmethod
    def new(cls, session_id: str, seed: int, created_at: datetime) -> SessionState:
        return cls(
            id=session_id,
            created_at=created_at,
            step=Step.SURVEY,
            seed=seed,
            survey=None,
            self_assess_level=None,
            questions=(),
            answers=(),
        )
```

- [ ] **Step 4: Ids aleatorios y carpeta exclusiva**

En `src/opic/session/store.py`, añadir `import re` y `import secrets`, y
sustituir `new_session_id` y `create`:

```python
# El id es la única cosa que separa el examen de un candidato del de otro:
# `GET /api/sessions/{id}` no comprueba quién pregunta. Mientras el nombre de
# máquina moría con cada túnel, una marca de tiempo era tolerable. Con un
# nombre permanente se recorre a mano, así que el id pasa a ser un secreto.
def new_session_id() -> str:
    return secrets.token_urlsafe(16)


# El formato de los ids anteriores a ese cambio. Sus carpetas no se renombran,
# así que hay que seguir sabiendo leerlas.
_LEGACY_ID = re.compile(r"^\d{8}-\d{6}$")


def create(root: Path, seed: int, now: datetime) -> SessionState:
    state = SessionState.new(new_session_id(), seed, now)
    # `exist_ok=False`: una colisión con 128 bits es imposible en la práctica,
    # y si ocurriera preferimos el error a dos exámenes en la misma carpeta.
    session_dir(root, state.id).mkdir(parents=True, exist_ok=False)
    save(root, state)
    return state
```

- [ ] **Step 5: Serializar la fecha, y derivarla cuando falta**

En `to_json`, junto a `"id"`:

```python
        "created_at": state.created_at.isoformat(),
```

Sustituir `from_json` y `load` (el resto del cuerpo de `from_json` no cambia):

```python
def load(root: Path, session_id: str) -> SessionState:
    path = session_dir(root, session_id) / SESSION_FILE
    if not path.exists():
        raise FileNotFoundError(f"no session {session_id!r} under {root}")
    # La fecha de modificación es el último recurso para una sesión anterior a
    # `created_at` cuyo nombre de carpeta tampoco es una marca de tiempo.
    fallback = datetime.fromtimestamp(path.stat().st_mtime)
    return from_json(json.loads(path.read_text(encoding="utf-8")), fallback)


def from_json(payload: dict, fallback: datetime | None = None) -> SessionState:
    return SessionState(
        id=payload["id"],
        created_at=_created_at(payload, fallback),
        ...  # el resto igual que ahora
    )


def _created_at(payload: dict, fallback: datetime | None) -> datetime:
    raw = payload.get("created_at")
    if raw:
        return datetime.fromisoformat(raw)
    if _LEGACY_ID.match(payload["id"]):
        return datetime.strptime(payload["id"], "%Y%m%d-%H%M%S")
    return fallback or datetime.min
```

- [ ] **Step 6: Ordenar por fecha, no por nombre**

```python
def list_unfinished(root: Path) -> tuple[str, ...]:
    """Sesiones con `session.json` y sin `result.json`, la más antigua primero.

    Ordenar por nombre dejó de servir cuando el id dejó de ser una marca de
    tiempo, así que esto lee cada sesión. Con miles de carpetas seguiría siendo
    trivial; si algún día no lo fuera, la fecha ya está en el JSON.
    """
    if not root.exists():
        return ()
    unfinished = []
    for directory in root.iterdir():
        if not (directory / SESSION_FILE).exists():
            continue
        if (directory / RESULT_FILE).exists():
            continue
        try:
            state = load(root, directory.name)
        except (OSError, ValueError, KeyError):
            continue
        unfinished.append((state.created_at, state.id))
    return tuple(session_id for _, session_id in sorted(unfinished))
```

- [ ] **Step 7: Ejecutar toda la suite**

Run: `uv run pytest -q`
Expected: PASS. Si algo falla en `tests/web` o `tests/session/test_worker.py`,
es porque construía un `SessionState` a mano sin `created_at`: añadirle
`created_at=datetime(2026, 8, 19, 14, 30, 52)`, no revertir el campo.

- [ ] **Step 8: Comprobar las sesiones reales**

Run:
```bash
uv run python -c "
from pathlib import Path
from opic.session import store
root = Path('data/sessions')
for name in sorted(p.name for p in root.iterdir() if (p / 'session.json').exists()):
    state = store.load(root, name)
    print(name, state.created_at.isoformat(), state.step.value)
"
```
Expected: las catorce líneas, cada una con una fecha que coincide con el nombre
de la carpeta. Ninguna excepción.

- [ ] **Step 9: Commit**

```bash
git add src/opic/session/state.py src/opic/session/store.py tests/session/test_store.py
git commit -m "feat(session): unguessable ids, and the date in the file instead"
```

---

### Task 2: `Candidate` y el paso de identidad

Cierra §4.1 y §4.2 del diseño. Todo puro: sin HTTP, sin disco.

**Files:**
- Create: `src/opic/core/candidate.py`
- Create: `tests/core/test_candidate.py`
- Modify: `src/opic/session/state.py` (`Step`, `ORDER`, `SessionState`)
- Modify: `src/opic/session/store.py` (`to_json`, `from_json`)
- Test: `tests/session/test_state.py`, `tests/session/test_store.py`

**Interfaces:**
- Consumes: `SessionState.created_at` de la Task 1.
- Produces:
  - `opic.core.candidate.Candidate(name: str, email: str)` — frozen, slots.
  - `opic.core.candidate.CandidateError` — enum con `EMPTY_NAME`, `LONG_NAME`,
    `BAD_EMAIL`, `LONG_EMAIL`.
  - `validate_candidate(name: str, email: str) -> tuple[CandidateError, ...]`
  - `describe_candidate_error_ko(error: CandidateError) -> str`
  - `Step.IDENTITY` con valor `"identity"`, primero en `ORDER`.
  - `SessionState.candidate: Candidate | None`
  - `SessionState.with_candidate(candidate: Candidate) -> SessionState`

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/core/test_candidate.py`:

```python
from __future__ import annotations

import pytest

from opic.core.candidate import (
    CandidateError,
    describe_candidate_error_ko,
    validate_candidate,
)


def test_a_name_and_a_plausible_address_pass():
    assert validate_candidate("김민준", "minjun@example.com") == ()


@pytest.mark.parametrize(
    "name, email, expected",
    [
        ("", "a@b.com", CandidateError.EMPTY_NAME),
        ("   ", "a@b.com", CandidateError.EMPTY_NAME),
        ("김" * 201, "a@b.com", CandidateError.LONG_NAME),
        ("김민준", "", CandidateError.BAD_EMAIL),
        ("김민준", "minjun", CandidateError.BAD_EMAIL),
        ("김민준", "min jun@example.com", CandidateError.BAD_EMAIL),
        ("김민준", "a@b@example.com", CandidateError.BAD_EMAIL),
        ("김민준", "@example.com", CandidateError.BAD_EMAIL),
        ("김민준", "minjun@", CandidateError.BAD_EMAIL),
        ("김민준", "minjun@example", CandidateError.BAD_EMAIL),
        ("김민준", "a" * 195 + "@b.com", CandidateError.LONG_EMAIL),
    ],
)
def test_what_is_refused(name, email, expected):
    assert expected in validate_candidate(name, email)


def test_every_error_has_korean_to_show():
    for error in CandidateError:
        assert describe_candidate_error_ko(error).strip()
```

Añadir a `tests/session/test_state.py`:

```python
def test_a_new_session_starts_at_identity():
    state = SessionState.new("abc", 7, datetime(2026, 8, 31, 14, 0, 0))
    assert state.step is Step.IDENTITY
    assert state.candidate is None


def test_identity_advances_to_survey():
    state = SessionState.new("abc", 7, datetime(2026, 8, 31, 14, 0, 0))
    named = state.with_candidate(Candidate("김민준", "minjun@example.com"))
    assert advance(named, Step.SURVEY).step is Step.SURVEY
    assert named.candidate.email == "minjun@example.com"


def test_identity_cannot_be_skipped():
    state = SessionState.new("abc", 7, datetime(2026, 8, 31, 14, 0, 0))
    with pytest.raises(TransitionError):
        advance(state, Step.LEVEL)
```

Añadir a `tests/session/test_store.py`:

```python
def test_the_candidate_survives_the_round_trip(tmp_path: Path):
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 31, 14, 0, 0))
    state = state.with_candidate(Candidate("김민준", "minjun@example.com"))
    store.save(tmp_path, state)
    assert store.load(tmp_path, state.id).candidate == Candidate("김민준", "minjun@example.com")


def test_a_session_saved_before_candidates_existed_loads_without_one(tmp_path: Path):
    state = store.create(tmp_path, seed=7, now=datetime(2026, 8, 31, 14, 0, 0))
    payload = json.loads((tmp_path / state.id / "session.json").read_text(encoding="utf-8"))
    del payload["candidate"]
    (tmp_path / state.id / "session.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    assert store.load(tmp_path, state.id).candidate is None
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `uv run pytest tests/core/test_candidate.py tests/session/test_state.py tests/session/test_store.py -v`
Expected: FAIL — `No module named 'opic.core.candidate'`.

- [ ] **Step 3: Escribir `core/candidate.py`**

```python
"""Quién se está examinando: un nombre y un correo, y qué se acepta como tales.

Esto no autentica a nadie. El correo es la etiqueta con la que se encuentra el
examen después, no una credencial ni un canal: no se verifica, no se envía nada
a él y dos candidatos pueden escribir el mismo. Lo que se comprueba aquí es
sólo que tiene forma de dirección, para que una errata evidente se vea en la
pantalla y no tres semanas después en la hoja de cálculo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

MAX_NAME = 200
MAX_EMAIL = 200


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    email: str


class CandidateError(Enum):
    EMPTY_NAME = "empty_name"
    LONG_NAME = "long_name"
    BAD_EMAIL = "bad_email"
    LONG_EMAIL = "long_email"


_MESSAGES_KO = {
    CandidateError.EMPTY_NAME: "이름을 입력해 주세요.",
    CandidateError.LONG_NAME: "이름이 너무 깁니다. 200자 이내로 입력해 주세요.",
    CandidateError.BAD_EMAIL: "이메일 주소를 다시 확인해 주세요. 예: name@example.com",
    CandidateError.LONG_EMAIL: "이메일 주소가 너무 깁니다. 200자 이내로 입력해 주세요.",
}


def describe_candidate_error_ko(error: CandidateError) -> str:
    return _MESSAGES_KO[error]


def _email_has_shape(email: str) -> bool:
    if not email or any(character.isspace() for character in email):
        return False
    local, separator, domain = email.partition("@")
    if not separator or "@" in domain:
        return False
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


def validate_candidate(name: str, email: str) -> tuple[CandidateError, ...]:
    issues: list[CandidateError] = []
    if not name.strip():
        issues.append(CandidateError.EMPTY_NAME)
    elif len(name) > MAX_NAME:
        issues.append(CandidateError.LONG_NAME)
    if len(email) > MAX_EMAIL:
        issues.append(CandidateError.LONG_EMAIL)
    elif not _email_has_shape(email):
        issues.append(CandidateError.BAD_EMAIL)
    return tuple(issues)
```

- [ ] **Step 4: El paso nuevo en la máquina de estados**

En `src/opic/session/state.py`, importar `Candidate` junto a `SurveyAnswers`:

```python
from opic.core.candidate import Candidate
```

Añadir el valor al principio de `Step` y de `ORDER`:

```python
class Step(Enum):
    IDENTITY = "identity"
    SURVEY = "survey"
    ...


ORDER: tuple[Step, ...] = (
    Step.IDENTITY,
    Step.SURVEY,
    ...
)
```

En `SessionState`, junto a `survey`:

```python
    candidate: Candidate | None
```

`new` empieza en el paso nuevo:

```python
            step=Step.IDENTITY,
            candidate=None,
```

Y el mutador, junto a `with_survey`:

```python
    def with_candidate(self, candidate: Candidate) -> SessionState:
        return replace(self, candidate=candidate)
```

> Las catorce sesiones guardadas no se rompen: `ORDER` sólo dice qué paso sigue
> a cuál, y ninguna está en `IDENTITY`. Una sesión antigua parada en `SURVEY`
> avanza exactamente igual que antes.

- [ ] **Step 5: Serializarlo**

En `store.py`, importar `Candidate` y añadir a `to_json`:

```python
        "candidate": (
            None
            if state.candidate is None
            else {"name": state.candidate.name, "email": state.candidate.email}
        ),
```

Y en `from_json`:

```python
        candidate=_candidate_from_json(payload.get("candidate")),
```

```python
def _candidate_from_json(payload: dict | None) -> Candidate | None:
    if payload is None:
        return None
    return Candidate(name=payload["name"], email=payload["email"])
```

- [ ] **Step 6: Ejecutar las pruebas**

Run: `uv run pytest tests/core/test_candidate.py tests/session -v`
Expected: PASS.

- [ ] **Step 7: Ejecutar la suite entera y arreglar lo que arrastre**

Run: `uv run pytest -q`
Expected: fallan las pruebas de `tests/web` que crean una sesión y esperan que
empiece en `survey`. **No revertir el paso.** Las fixtures de
`tests/web/conftest.py` se arreglan en la Task 3; hasta entonces se admite el
fallo en `tests/web`, y `tests/core`, `tests/session` y `tests/adapters` deben
pasar.

Run: `uv run pytest tests/core tests/session tests/adapters -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/opic/core/candidate.py tests/core/test_candidate.py \
        src/opic/session/state.py src/opic/session/store.py \
        tests/session/test_state.py tests/session/test_store.py
git commit -m "feat(session): a name and an email on every exam"
```

---

### Task 3: El endpoint y la pantalla de identidad

Cierra §4.3 y §4.4. Deja el examen otra vez completo de punta a punta.

**Files:**
- Modify: `src/opic/web/app.py` (imports, `IdentityPayload`, `put_identity`)
- Create: `src/opic/web/static/steps/identity.js`
- Modify: `src/opic/web/static/app.js` (`LABELS`, lista de módulos)
- Modify: `tests/web/conftest.py` (fixtures `session_id` y una nueva)
- Create: `tests/web/test_identity_route.py`

**Interfaces:**
- Consumes: `Candidate`, `validate_candidate`, `describe_candidate_error_ko`,
  `Step.IDENTITY` de la Task 2.
- Produces:
  - `PUT /api/sessions/{id}/identity`, cuerpo `{"name": str, "email": str}`,
    devuelve el estado de la sesión como los demás endpoints.
  - Fixture `identified` en `tests/web/conftest.py`: `(client, session_id)` con
    la identidad ya enviada, sobre la que se apoyan las demás fixtures.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/web/test_identity_route.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def test_a_new_session_asks_for_the_identity_first(client: TestClient):
    created = client.post("/api/sessions").json()
    assert created["step"] == "identity"
    assert created["candidate"] is None


def test_sending_it_advances_to_the_survey(client: TestClient):
    session_id = client.post("/api/sessions").json()["id"]
    response = client.put(
        f"/api/sessions/{session_id}/identity",
        json={"name": "김민준", "email": "minjun@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["step"] == "survey"
    assert body["candidate"] == {"name": "김민준", "email": "minjun@example.com"}


def test_a_bad_address_comes_back_with_korean_to_show(client: TestClient):
    session_id = client.post("/api/sessions").json()["id"]
    response = client.put(
        f"/api/sessions/{session_id}/identity",
        json={"name": "김민준", "email": "minjun"},
    )
    assert response.status_code == 422
    issue = response.json()["issues"][0]
    assert issue["error"] == "bad_email"
    assert issue["message_ko"].strip()


def test_the_survey_is_refused_before_the_identity(client: TestClient, a_valid_survey: dict):
    session_id = client.post("/api/sessions").json()["id"]
    response = client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    assert response.status_code == 409


def test_surrounding_whitespace_is_trimmed(client: TestClient):
    session_id = client.post("/api/sessions").json()["id"]
    body = client.put(
        f"/api/sessions/{session_id}/identity",
        json={"name": "  김민준  ", "email": "  minjun@example.com  "},
    ).json()
    assert body["candidate"] == {"name": "김민준", "email": "minjun@example.com"}


def test_sending_it_twice_is_refused(client: TestClient):
    session_id = client.post("/api/sessions").json()["id"]
    payload = {"name": "김민준", "email": "minjun@example.com"}
    client.put(f"/api/sessions/{session_id}/identity", json=payload)
    assert client.put(f"/api/sessions/{session_id}/identity", json=payload).status_code == 409
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `uv run pytest tests/web/test_identity_route.py -v`
Expected: FAIL — 404 en `/identity`, porque la ruta no existe.

- [ ] **Step 3: El endpoint**

En `src/opic/web/app.py`, añadir al bloque de imports de `opic.core`:

```python
from opic.core.candidate import (
    Candidate,
    describe_candidate_error_ko,
    validate_candidate,
)
```

Junto a `LevelPayload`:

```python
class IdentityPayload(BaseModel):
    name: str
    email: str
```

Y la ruta, inmediatamente antes de `put_survey`:

```python
    @app.put("/api/sessions/{session_id}/identity")
    def put_identity(session_id: str, payload: IdentityPayload):
        state = load_or_404(session_id)
        if state.step is not Step.IDENTITY:
            raise HTTPException(
                status_code=409,
                detail=f"expected step identity, session is at {state.step.value}",
            )
        name = payload.name.strip()
        email = payload.email.strip()
        issues = validate_candidate(name, email)
        if issues:
            return JSONResponse(
                status_code=422,
                content={
                    "issues": [
                        {
                            "error": issue.value,
                            "detail": "",
                            "message_ko": describe_candidate_error_ko(issue),
                        }
                        for issue in issues
                    ]
                },
            )
        state = worker.update(
            session_id,
            lambda s: advance(s.with_candidate(Candidate(name, email)), Step.SURVEY),
        )
        return session_json(state)
```

- [ ] **Step 4: Arreglar las fixtures de `tests/web`**

En `tests/web/conftest.py`, la fixture `session_id` crea la sesión y va directa
a la encuesta. Ahora tiene que identificarse primero. Sustituirla por:

```python
@pytest.fixture
def identified(client: TestClient) -> str:
    """Una sesión con la identidad ya enviada, parada en la encuesta."""
    session_id = client.post("/api/sessions").json()["id"]
    client.put(
        f"/api/sessions/{session_id}/identity",
        json={"name": "김민준", "email": "minjun@example.com"},
    )
    return session_id


@pytest.fixture
def session_id(client: TestClient, worker: Worker, identified: str, a_valid_survey: dict) -> str:
    """A session that has reached the TEST step, ready to receive answers."""
    session_id = identified
    client.put(f"/api/sessions/{session_id}/survey", json=a_valid_survey)
    client.put(f"/api/sessions/{session_id}/level", json={"level": 4})
    worker.drain()
    for step in ("sample", "test"):
        client.post(f"/api/sessions/{session_id}/step", json={"step": step})
    return session_id
```

Además, el comentario de la fixture `client` («A client whose clock is frozen,
so session ids are predictable») ya no es cierto desde la Task 1. Cambiarlo por:

```python
    """A client whose clock is frozen, so `created_at` is predictable.

    The id is random now, so nothing here may hardcode one: read it from the
    response.
    """
```

Buscar cualquier prueba que sí lo tuviera escrito a mano:

Run: `grep -rn "20260819-143052" tests/`
Cualquier coincidencia que sea un id de sesión (no un `created_at` ni un
`datetime`) se sustituye por el id leído de la respuesta.

- [ ] **Step 5: Ejecutar la suite entera**

Run: `uv run pytest -q`
Expected: PASS, todo.

- [ ] **Step 6: La pantalla**

Crear `src/opic/web/static/steps/identity.js`, siguiendo el patrón de
`level.js`:

```javascript
// Paso 0 — quién se examina. No es un registro: el correo es la etiqueta con
// la que este examen se encuentra después, en la hoja de cálculo y en la
// consola. No se verifica y no se le envía nada.
export async function render(state, {api, show}) {
  const form = document.createElement("form");

  const heading = document.createElement("h2");
  heading.textContent = "시작하기 전에";

  const note = document.createElement("p");
  note.textContent =
    "결과 리포트를 찾을 때 사용합니다. 확인 메일은 보내지 않습니다.";

  const nameLabel = document.createElement("label");
  const name = document.createElement("input");
  name.type = "text";
  name.name = "name";
  name.required = true;
  name.autocomplete = "name";
  name.maxLength = 200;
  nameLabel.append("이름 ", name);

  const emailLabel = document.createElement("label");
  const email = document.createElement("input");
  email.type = "email";
  email.name = "email";
  email.required = true;
  email.autocomplete = "email";
  email.maxLength = 200;
  emailLabel.append("이메일 ", email);

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "다음";

  const status = document.createElement("p");
  status.className = "issues";

  form.append(heading, note, nameLabel, emailLabel, submit, status);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    status.textContent = "";
    const data = new FormData(form);
    try {
      await show(
        await api.send("PUT", `/api/sessions/${state.id}/identity`, {
          name: String(data.get("name")),
          email: String(data.get("email")),
        }),
      );
    } catch (error) {
      // 422 trae `issues` con el coreano ya escrito por el servidor; cualquier
      // otra cosa es la red.
      const issues = error.payload?.issues;
      status.textContent = issues?.length
        ? issues.map((issue) => issue.message_ko).join(" ")
        : "서버와 연결할 수 없습니다. 다시 시도해 주세요.";
      submit.disabled = false;
    }
  });

  document.getElementById("app").replaceChildren(form);
}
```

- [ ] **Step 7: Registrar el paso**

En `src/opic/web/static/app.js`, añadir la etiqueta al principio de `LABELS`:

```javascript
  identity: "시작 · 응시자 정보",
```

Y `"identity"` al principio de la lista de módulos que se importan:

```javascript
for (const name of ["identity", "survey", "level", "setup", "sample", "test", "grading", "done"]) {
```

- [ ] **Step 8: Comprobarlo en el navegador**

Run: `uv run python -m opic.cli --serve`
Abrir `http://localhost:8000` en una ventana privada (para no arrastrar el
`localStorage` de una sesión anterior) y comprobar, en este orden:
1. La primera pantalla pide nombre y correo.
2. Un correo sin `@` muestra el mensaje en coreano y no avanza.
3. Uno correcto lleva a la encuesta.
4. `data/sessions/<id>/session.json` contiene el bloque `candidate`.

Ctrl-C al terminar.

- [ ] **Step 9: Commit**

```bash
git add src/opic/web/app.py src/opic/web/static/steps/identity.js \
        src/opic/web/static/app.js tests/web/conftest.py \
        tests/web/test_identity_route.py
git commit -m "feat(web): ask who is taking the exam before it starts"
```

---

### Task 4: Encontrar un examen desde la consola

Cierra la segunda mitad de §6. Sin endpoint y sin superficie de red nueva.

**Files:**
- Modify: `src/opic/cli.py` (`find_sessions`, `main`)
- Create: `tests/test_cli_find.py`

**Interfaces:**
- Consumes: `SessionState.candidate` y `created_at` de las Tasks 1 y 2.
- Produces: `cli.find_sessions(root: Path, needle: str, out=print) -> int` —
  devuelve 0 aunque no encuentre nada; una búsqueda vacía no es un error.

- [ ] **Step 1: Escribir la prueba que falla**

Crear `tests/test_cli_find.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from opic.cli import find_sessions
from opic.core.candidate import Candidate
from opic.session import store


def _a_session(root: Path, name: str, email: str, when: datetime) -> str:
    state = store.create(root, seed=1, now=when)
    store.save(root, state.with_candidate(Candidate(name, email)))
    return state.id


def test_it_finds_by_email(tmp_path: Path):
    wanted = _a_session(tmp_path, "김민준", "minjun@example.com", datetime(2026, 8, 31, 9, 0))
    _a_session(tmp_path, "이서연", "seoyeon@example.com", datetime(2026, 8, 31, 10, 0))
    lines: list[str] = []
    assert find_sessions(tmp_path, "minjun", out=lines.append) == 0
    printed = "\n".join(lines)
    assert wanted in printed
    assert "seoyeon" not in printed


def test_it_finds_by_name_and_ignores_case(tmp_path: Path):
    wanted = _a_session(tmp_path, "Minjun Kim", "m@example.com", datetime(2026, 8, 31, 9, 0))
    lines: list[str] = []
    find_sessions(tmp_path, "MINJUN", out=lines.append)
    assert wanted in "\n".join(lines)


def test_nothing_found_is_not_an_error(tmp_path: Path):
    _a_session(tmp_path, "김민준", "minjun@example.com", datetime(2026, 8, 31, 9, 0))
    lines: list[str] = []
    assert find_sessions(tmp_path, "nobody", out=lines.append) == 0
    assert any("0" in line for line in lines)


def test_a_session_with_no_candidate_does_not_crash_it(tmp_path: Path):
    store.create(tmp_path, seed=1, now=datetime(2026, 8, 31, 9, 0))
    lines: list[str] = []
    assert find_sessions(tmp_path, "minjun", out=lines.append) == 0
```

- [ ] **Step 2: Ejecutar y ver que falla**

Run: `uv run pytest tests/test_cli_find.py -v`
Expected: FAIL — `cannot import name 'find_sessions'`.

- [ ] **Step 3: Implementarlo**

En `src/opic/cli.py`, junto a `regenerate_report`:

```python
def find_sessions(root: Path, needle: str, out=print) -> int:
    """Listar los exámenes cuyo nombre o correo contienen `needle`.

    Vive en la consola y no en la API a propósito: todos los invitados
    comparten el mismo token de la puerta, así que un endpoint de listado le
    enseñaría a cualquiera de ellos los exámenes de todos los demás.
    """
    wanted = needle.strip().lower()
    if not root.exists():
        out(f"no hay sesiones en {root}")
        return 0

    rows = []
    for directory in sorted(root.iterdir()):
        if not (directory / store.SESSION_FILE).exists():
            continue
        try:
            state = store.load(root, directory.name)
        except (OSError, ValueError, KeyError):
            continue
        if state.candidate is None:
            continue
        haystack = f"{state.candidate.name} {state.candidate.email}".lower()
        if wanted not in haystack:
            continue
        level = ""
        result = store.result_path(root, state.id)
        if result.exists():
            try:
                level = json.loads(result.read_text(encoding="utf-8")).get("final_level", "")
            except (OSError, ValueError):
                level = "?"
        rows.append((state.created_at, state.id, state.candidate, state.step.value, level))

    for created_at, session_id, candidate, step, level in sorted(rows):
        out(
            f"{created_at:%Y-%m-%d %H:%M}  {session_id}  "
            f"{candidate.name} <{candidate.email}>  {step}  {level}"
        )
    out(f"{len(rows)} sesión(es)")
    return 0
```

Comprobar que `json`, `Path` y `store` ya están importados arriba en `cli.py`;
si `store` no lo está, añadir `from opic.session import store`.

- [ ] **Step 4: Engancharlo a la línea de órdenes**

En `main`, junto a los otros `add_argument`:

```python
    parser.add_argument(
        "--find",
        metavar="TEXT",
        help="list sessions whose candidate name or email contains TEXT, and exit",
    )
    parser.add_argument(
        "--sessions-root",
        type=Path,
        default=Path("data/sessions"),
        help="where sessions live; used by --find and --publish",
    )
```

Y el despacho, inmediatamente antes del bloque de `--report`:

```python
    if args.find is not None:
        return find_sessions(args.sessions_root, args.find)
```

- [ ] **Step 5: Ejecutar las pruebas**

Run: `uv run pytest tests/test_cli_find.py tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 6: Probarlo contra las sesiones reales**

Run: `uv run python -m opic.cli --find @`
Expected: las sesiones que ya tengan identidad (ninguna todavía, si aún no has
hecho un examen desde la Task 3) y la línea del recuento. Sin excepciones.

- [ ] **Step 7: Commit**

```bash
git add src/opic/cli.py tests/test_cli_find.py
git commit -m "feat(cli): --find, to get at an exam by name or email"
```

---

### Task 5: El puerto y el adaptador de la hoja

Cierra §8.3. Sin dependencias nuevas y sin red en las pruebas.

**Files:**
- Modify: `src/opic/core/ports.py` (`SheetSink`)
- Create: `src/opic/adapters/sheets.py`
- Create: `tests/adapters/test_sheets.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `opic.core.ports.SheetSink` — protocolo con `append(row: dict[str, str]) -> None`.
  - `opic.adapters.sheets.NullSheet` — implementación que no hace nada.
  - `opic.adapters.sheets.AppsScriptSheet(url: str, opener=urllib.request.urlopen, timeout: float = 20.0)`.
  - `opic.adapters.sheets.SheetError` — `RuntimeError`.
  - `opic.adapters.sheets.make_sheet_sink(url: str | None = None) -> SheetSink`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/adapters/test_sheets.py`:

```python
from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from opic.adapters.sheets import (
    AppsScriptSheet,
    NullSheet,
    SheetError,
    make_sheet_sink,
)


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


def recording_opener(status: int = 200):
    """Un doble de `urlopen`: guarda la petición y no toca la red."""
    seen = []

    @contextmanager
    def opener(request, timeout=None):
        seen.append((request, timeout))
        yield FakeResponse(status)

    opener.seen = seen
    return opener


def test_it_posts_the_row_as_json():
    opener = recording_opener()
    AppsScriptSheet("https://script.google.com/macros/s/xyz/exec", opener=opener).append(
        {"email": "minjun@example.com", "rating": "5"}
    )
    request, timeout = opener.seen[0]
    assert request.method == "POST"
    assert request.full_url == "https://script.google.com/macros/s/xyz/exec"
    assert request.headers["Content-type"] == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "email": "minjun@example.com",
        "rating": "5",
    }
    assert timeout == 20.0


def test_a_refusal_raises_so_the_worker_retries():
    opener = recording_opener(status=500)
    with pytest.raises(SheetError):
        AppsScriptSheet("https://example.com/hook", opener=opener).append({"a": "b"})


def test_the_null_sink_swallows_everything():
    assert NullSheet().append({"a": "b"}) is None


def test_no_url_means_the_null_sink(monkeypatch):
    monkeypatch.delenv("OPIC_SHEET_URL", raising=False)
    assert isinstance(make_sheet_sink(), NullSheet)


def test_a_blank_url_means_the_null_sink(monkeypatch):
    monkeypatch.setenv("OPIC_SHEET_URL", "   ")
    assert isinstance(make_sheet_sink(), NullSheet)


def test_a_url_in_the_environment_is_used(monkeypatch):
    monkeypatch.setenv("OPIC_SHEET_URL", "https://example.com/hook")
    assert isinstance(make_sheet_sink(), AppsScriptSheet)
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `uv run pytest tests/adapters/test_sheets.py -v`
Expected: FAIL — `No module named 'opic.adapters.sheets'`.

- [ ] **Step 3: El puerto**

En `src/opic/core/ports.py`, junto a los demás protocolos:

```python
class SheetSink(Protocol):
    """Dónde va a parar una fila de resultados. Una hoja de cálculo, o nada."""

    def append(self, row: dict[str, str]) -> None: ...
```

- [ ] **Step 4: El adaptador**

Crear `src/opic/adapters/sheets.py`:

```python
"""Una fila por examen, enviada a un webhook de Apps Script.

Se eligió Apps Script y no la API de Sheets porque no necesita proyecto de
GCP, ni fichero de credenciales, ni dependencia nueva: una petición POST con
`urllib` de la biblioteca estándar. Lo que se paga por eso es que la URL es el
secreto entero — quien la tenga puede añadir filas — así que vive en `.env`
junto a la clave de la API y nunca en git.

Apps Script contesta con una redirección a `script.googleusercontent.com`, que
`urllib` sigue sola. No hace falta leer el cuerpo: lo único que importa aquí es
que la fila se escribió.
"""

from __future__ import annotations

import json
import os
import urllib.request

DEFAULT_TIMEOUT_S = 20.0


class SheetError(RuntimeError):
    """La hoja no aceptó la fila."""


class NullSheet:
    """Sin `OPIC_SHEET_URL` no hay hoja, y eso no es un fallo.

    Es lo que hace que las pruebas y cualquier ejecución local no escriban en
    la hoja de nadie, sin condicionales repartidos por el worker.
    """

    def append(self, row: dict[str, str]) -> None:
        return None


class AppsScriptSheet:
    def __init__(
        self,
        url: str,
        opener=urllib.request.urlopen,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._url = url
        self._opener = opener
        self._timeout = timeout

    def append(self, row: dict[str, str]) -> None:
        request = urllib.request.Request(
            self._url,
            data=json.dumps(row, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                status = getattr(response, "status", 200)
        except OSError as error:
            raise SheetError(f"the sheet did not answer: {error}") from error
        if status >= 400:
            raise SheetError(f"the sheet answered {status}")


def make_sheet_sink(url: str | None = None) -> NullSheet | AppsScriptSheet:
    """`OPIC_SHEET_URL` decide, con el mismo patrón que `OPIC_LLM`."""
    resolved = (url if url is not None else os.environ.get("OPIC_SHEET_URL", "")).strip()
    return AppsScriptSheet(resolved) if resolved else NullSheet()
```

- [ ] **Step 5: Ejecutar las pruebas**

Run: `uv run pytest tests/adapters/test_sheets.py tests/core/test_ports.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opic/core/ports.py src/opic/adapters/sheets.py tests/adapters/test_sheets.py
git commit -m "feat(adapters): a sheet sink over an Apps Script webhook"
```

---

### Task 6: El feedback, del navegador a la hoja

Cierra §8.1 (datos), §8.2 y §8.4. La tarjeta del navegador es la Task 7.

**Files:**
- Modify: `src/opic/session/state.py` (`Feedback`, `SessionState.feedback`,
  `with_feedback`)
- Modify: `src/opic/session/store.py` (`to_json`, `from_json`)
- Create: `src/opic/session/publish.py`
- Modify: `src/opic/session/worker.py` (`PUBLISH`, `__init__`, `run_one`, `_publish`)
- Modify: `src/opic/web/app.py` (`FeedbackPayload`, `post_feedback`)
- Modify: `src/opic/web/serve.py` (pasar el sumidero y la URL pública al worker)
- Create: `tests/session/test_publish.py`
- Create: `tests/web/test_feedback_route.py`
- Modify: `tests/doubles.py` (`FakeSheet`, `ExplodingSheet`)

**Interfaces:**
- Consumes: `SheetSink`, `make_sheet_sink` de la Task 5; `Candidate` de la
  Task 2; `created_at` de la Task 1.
- Produces:
  - `state.Feedback(rating: int, comment: str, published: bool = False)`
  - `SessionState.feedback: Feedback | None`, `with_feedback(feedback) -> SessionState`
  - `session.publish.sheet_row(state: SessionState, result: dict | None, public_url: str) -> dict[str, str]`
  - `worker.PUBLISH = "publish"`, y `Worker(..., sheet: SheetSink | None = None, public_url: str = "")`
  - `POST /api/sessions/{id}/feedback`, cuerpo `{"rating": int, "comment": str}`,
    responde `202 {"ok": true}`.

- [ ] **Step 1: Escribir las pruebas que fallan (la fila)**

Crear `tests/session/test_publish.py`:

```python
from __future__ import annotations

from datetime import datetime

from opic.core.candidate import Candidate
from opic.session.publish import sheet_row
from opic.session.state import Feedback, SessionState


def a_state() -> SessionState:
    state = SessionState.new("Nk7Qz", 1, datetime(2026, 8, 31, 14, 30, 52))
    state = state.with_candidate(Candidate("김민준", "minjun@example.com"))
    return state.with_feedback(Feedback(rating=5, comment="좋았습니다"))


def test_every_column_is_filled_from_the_session():
    row = sheet_row(a_state(), {"final_level": "IH"}, "https://opic.example.com")
    assert row == {
        "timestamp": "2026-08-31T14:30:52",
        "session_id": "Nk7Qz",
        "name": "김민준",
        "email": "minjun@example.com",
        "level": "IH",
        "rating": "5",
        "comment": "좋았습니다",
        "report_url": "https://opic.example.com/api/sessions/Nk7Qz/page",
    }


def test_an_exam_that_never_got_a_grade_leaves_the_level_empty():
    assert sheet_row(a_state(), None, "https://opic.example.com")["level"] == ""


def test_without_a_public_url_there_is_no_link_to_offer():
    assert sheet_row(a_state(), {"final_level": "IH"}, "")["report_url"] == ""


def test_a_trailing_slash_does_not_double_up():
    row = sheet_row(a_state(), None, "https://opic.example.com/")
    assert row["report_url"] == "https://opic.example.com/api/sessions/Nk7Qz/page"


def test_a_session_with_no_candidate_still_makes_a_row():
    state = SessionState.new("Nk7Qz", 1, datetime(2026, 8, 31, 14, 30, 52))
    row = sheet_row(state.with_feedback(Feedback(3, "")), None, "")
    assert row["name"] == ""
    assert row["email"] == ""
    assert row["rating"] == "3"
```

- [ ] **Step 2: Ejecutar y ver que falla**

Run: `uv run pytest tests/session/test_publish.py -v`
Expected: FAIL — `cannot import name 'Feedback'`.

- [ ] **Step 3: `Feedback` en el estado**

En `src/opic/session/state.py`, junto a `AnswerRecord`:

```python
@dataclass(frozen=True, slots=True)
class Feedback:
    """Lo que el candidato opina, y si ya llegó a la hoja.

    `published` es lo que permite reintentar sin duplicar filas: la tarea de
    publicación lo comprueba antes de enviar y lo marca después.
    """

    rating: int
    comment: str
    published: bool = False
```

En `SessionState`, junto a `candidate`:

```python
    feedback: Feedback | None
```

En `new`:

```python
            feedback=None,
```

Y el mutador:

```python
    def with_feedback(self, feedback: Feedback) -> SessionState:
        return replace(self, feedback=feedback)
```

- [ ] **Step 4: Serializarlo**

En `store.py`, importar `Feedback` y añadir a `to_json`:

```python
        "feedback": (
            None
            if state.feedback is None
            else {
                "rating": state.feedback.rating,
                "comment": state.feedback.comment,
                "published": state.feedback.published,
            }
        ),
```

En `from_json`:

```python
        feedback=_feedback_from_json(payload.get("feedback")),
```

```python
def _feedback_from_json(payload: dict | None) -> Feedback | None:
    if payload is None:
        return None
    return Feedback(
        rating=payload["rating"],
        comment=payload["comment"],
        published=payload.get("published", False),
    )
```

- [ ] **Step 5: La fila**

Crear `src/opic/session/publish.py`:

```python
"""Una sesión, vista como una fila de hoja de cálculo.

Puro: recibe el estado y el `result.json` ya leído, y devuelve un diccionario
de cadenas. Quien lo llama es el que toca el disco y la red.
"""

from __future__ import annotations

from opic.session.state import SessionState


def sheet_row(state: SessionState, result: dict | None, public_url: str) -> dict[str, str]:
    candidate = state.candidate
    feedback = state.feedback
    base = public_url.rstrip("/")
    return {
        "timestamp": state.created_at.isoformat(),
        "session_id": state.id,
        "name": candidate.name if candidate else "",
        "email": candidate.email if candidate else "",
        "level": str(result.get("final_level", "")) if result else "",
        "rating": str(feedback.rating) if feedback else "",
        "comment": feedback.comment if feedback else "",
        # Sin URL pública no hay enlace que ofrecer: el servidor no puede saber
        # por sí mismo bajo qué nombre lo ven desde fuera.
        "report_url": f"{base}/api/sessions/{state.id}/page" if base else "",
    }
```

- [ ] **Step 6: Ejecutar y ver que pasa**

Run: `uv run pytest tests/session/test_publish.py -v`
Expected: PASS.

- [ ] **Step 7: Escribir las pruebas que fallan (la tarea del worker)**

Añadir a `tests/doubles.py`:

```python
class FakeSheet:
    """Guarda las filas en vez de enviarlas."""

    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    def append(self, row: dict[str, str]) -> None:
        self.rows.append(row)


class ExplodingSheet:
    """Falla siempre, para comprobar que el feedback no se pierde."""

    def __init__(self) -> None:
        self.calls = 0

    def append(self, row: dict[str, str]) -> None:
        self.calls += 1
        raise RuntimeError("the sheet is down")
```

Añadir a `tests/session/test_worker.py`:

```python
def test_publishing_sends_the_row_and_marks_it(tmp_path, ports):
    from doubles import FakeSheet

    sheet = FakeSheet()
    root = tmp_path / "sessions"
    worker = Worker(root=root, sheet=sheet, public_url="https://opic.example.com",
                    sleeper=lambda _: None, **ports)
    state = store.create(root, seed=1, now=datetime(2026, 8, 31, 14, 30, 52))
    worker.update(
        state.id,
        lambda s: s.with_candidate(Candidate("김민준", "minjun@example.com")).with_feedback(
            Feedback(5, "좋았습니다")
        ),
    )

    worker.run_one(Task("publish", state.id))

    assert len(sheet.rows) == 1
    assert sheet.rows[0]["email"] == "minjun@example.com"
    assert store.load(root, state.id).feedback.published is True


def test_publishing_twice_sends_one_row(tmp_path, ports):
    from doubles import FakeSheet

    sheet = FakeSheet()
    root = tmp_path / "sessions"
    worker = Worker(root=root, sheet=sheet, sleeper=lambda _: None, **ports)
    state = store.create(root, seed=1, now=datetime(2026, 8, 31, 14, 30, 52))
    worker.update(state.id, lambda s: s.with_feedback(Feedback(5, "")))

    worker.run_one(Task("publish", state.id))
    worker.run_one(Task("publish", state.id))

    assert len(sheet.rows) == 1


def test_a_sheet_that_is_down_leaves_the_feedback_unpublished(tmp_path, ports):
    from doubles import ExplodingSheet

    sheet = ExplodingSheet()
    root = tmp_path / "sessions"
    worker = Worker(root=root, sheet=sheet, retries=2, sleeper=lambda _: None, **ports)
    state = store.create(root, seed=1, now=datetime(2026, 8, 31, 14, 30, 52))
    worker.update(state.id, lambda s: s.with_feedback(Feedback(5, "좋았습니다")))

    with pytest.raises(RuntimeError):
        worker.run_one(Task("publish", state.id))

    assert sheet.calls == 2
    saved = store.load(root, state.id).feedback
    assert saved.published is False
    assert saved.comment == "좋았습니다"


def test_publishing_a_session_with_no_feedback_does_nothing(tmp_path, ports):
    from doubles import FakeSheet

    sheet = FakeSheet()
    root = tmp_path / "sessions"
    worker = Worker(root=root, sheet=sheet, sleeper=lambda _: None, **ports)
    state = store.create(root, seed=1, now=datetime(2026, 8, 31, 14, 30, 52))

    worker.run_one(Task("publish", state.id))

    assert sheet.rows == []
```

Comprobar los imports que ya tenga `tests/session/test_worker.py` y añadir los
que falten: `datetime`, `Candidate`, `Feedback`, `store`, `Task`, `Worker`,
`pytest`.

- [ ] **Step 8: Ejecutar y ver que fallan**

Run: `uv run pytest tests/session/test_worker.py -k publish -v`
Expected: FAIL — `Worker.__init__() got an unexpected keyword argument 'sheet'`.

- [ ] **Step 9: La tarea de publicación**

En `src/opic/session/worker.py`, añadir la constante junto a las otras:

```python
PUBLISH = "publish"
```

Los imports que faltan:

```python
from opic.adapters.sheets import NullSheet
from opic.core.ports import SheetSink
from opic.session.publish import sheet_row
from opic.session.state import Feedback
```

Dos parámetros nuevos en `Worker.__init__`, después de `narrator`:

```python
        sheet: SheetSink | None = None,
        public_url: str = "",
```

y en el cuerpo:

```python
        self._sheet = sheet or NullSheet()
        self._public_url = public_url
```

En `run_one`, antes del `else`:

```python
        elif task.kind == PUBLISH:
            self._publish(task.session_id)
```

Y el método, junto a `_aggregate`:

```python
    def _publish(self, session_id: str) -> None:
        """Mandar la fila del examen a la hoja, una sola vez.

        El feedback ya está en `session.json` cuando esto corre: el endpoint lo
        guarda antes de encolar la tarea. Si la hoja no contesta, `_attempt`
        acaba lanzando, el bucle del worker lo registra, y el feedback se queda
        en disco con `published: False` — que es lo que `--publish` reenvía.
        """
        state = store.load(self._root, session_id)
        if state.feedback is None or state.feedback.published:
            return
        result = None
        path = store.result_path(self._root, session_id)
        if path.exists():
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                result = None
        row = sheet_row(state, result, self._public_url)
        self._attempt(lambda: self._sheet.append(row))
        self.update(
            session_id,
            lambda s: s.with_feedback(replace(s.feedback, published=True)),
        )
```

`json` y `replace` ya están importados en `worker.py`.

- [ ] **Step 10: Ejecutar las pruebas del worker**

Run: `uv run pytest tests/session/test_worker.py -v`
Expected: PASS.

- [ ] **Step 11: Escribir las pruebas que fallan (el endpoint)**

Crear `tests/web/test_feedback_route.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from opic.session import store


def test_it_saves_the_feedback_and_answers(client: TestClient, worker, scored_session: str):
    response = client.post(
        f"/api/sessions/{scored_session}/feedback",
        json={"rating": 5, "comment": "좋았습니다"},
    )
    assert response.status_code == 202
    saved = store.load(worker._root, scored_session).feedback
    assert saved.rating == 5
    assert saved.comment == "좋았습니다"


def test_the_row_goes_out_when_the_worker_runs(client: TestClient, worker, scored_session: str):
    client.post(f"/api/sessions/{scored_session}/feedback", json={"rating": 4, "comment": ""})
    worker.drain()
    assert store.load(worker._root, scored_session).feedback.published is True


def test_a_rating_out_of_range_is_refused(client: TestClient, scored_session: str):
    response = client.post(
        f"/api/sessions/{scored_session}/feedback", json={"rating": 9, "comment": ""}
    )
    assert response.status_code == 422
    assert response.json()["issues"][0]["message_ko"].strip()


def test_a_very_long_comment_is_cut_not_refused(client: TestClient, worker, scored_session: str):
    client.post(
        f"/api/sessions/{scored_session}/feedback",
        json={"rating": 3, "comment": "가" * 5000},
    )
    assert len(store.load(worker._root, scored_session).feedback.comment) == 2000


def test_an_unknown_session_is_a_404(client: TestClient):
    response = client.post("/api/sessions/nope/feedback", json={"rating": 3, "comment": ""})
    assert response.status_code == 404
```

En `tests/web/conftest.py`, la fixture `worker` pasa a llevar la hoja falsa:

```python
@pytest.fixture
def sheet():
    from doubles import FakeSheet

    return FakeSheet()


@pytest.fixture
def worker(sessions_root: Path, tmp_path: Path, sheet) -> Worker:
    return Worker(
        root=sessions_root,
        tts=FakeTextToSpeech(tmp_path / "tts_cache"),
        stt=FakeSpeechToText(),
        writer=FakeQuestionWriter(),
        rater=FakeRater(),
        sheet=sheet,
        public_url="https://opic.example.com",
        sleeper=lambda _: None,
    )
```

- [ ] **Step 12: Ejecutar y ver que fallan**

Run: `uv run pytest tests/web/test_feedback_route.py -v`
Expected: FAIL — 404, la ruta no existe.

- [ ] **Step 13: El endpoint**

En `src/opic/web/app.py`, junto a `StepPayload`:

```python
class FeedbackPayload(BaseModel):
    rating: int
    comment: str = ""


# Un comentario más largo que esto no es una opinión, es un accidente (o un
# intento de llenar el disco). Se recorta en vez de rechazarse: el candidato ya
# terminó el examen y no va a volver a escribirlo.
MAX_COMMENT = 2000
```

Importar `Feedback`:

```python
from opic.session.state import AnswerRecord, AnswerState, Feedback, Step, TransitionError, advance
```

Y la ruta, después de `report_page`:

```python
    @app.post("/api/sessions/{session_id}/feedback", status_code=202)
    def post_feedback(session_id: str, payload: FeedbackPayload) -> dict:
        """Guardar la opinión del candidato, y sólo después intentar la hoja.

        El orden es lo importante: `worker.update` deja el feedback en
        `session.json` antes de que Google entre en la historia, así que el
        envío del candidato no espera a la red y no falla por ella.
        """
        load_or_404(session_id)
        if payload.rating not in range(1, 6):
            return JSONResponse(
                status_code=422,
                content={
                    "issues": [
                        {
                            "error": "bad_rating",
                            "detail": str(payload.rating),
                            "message_ko": "1점부터 5점 사이로 선택해 주세요.",
                        }
                    ]
                },
            )
        comment = payload.comment.strip()[:MAX_COMMENT]
        worker.update(
            session_id,
            lambda s: s.with_feedback(Feedback(rating=payload.rating, comment=comment)),
        )
        worker.submit(Task("publish", session_id))
        return {"ok": True}
```

- [ ] **Step 14: Conectarlo en el servidor real**

En `src/opic/web/serve.py`, importar y pasar los dos parámetros:

```python
from opic.adapters.sheets import make_sheet_sink
```

Dentro de `app()`, en la construcción del `Worker`:

```python
        sheet=make_sheet_sink(),
        # El servidor no puede saber bajo qué nombre lo ven desde fuera; sin
        # esto la fila va a la hoja sin enlace al informe, que es peor pero no
        # es un fallo.
        public_url=os.environ.get("OPIC_PUBLIC_URL", "").strip(),
```

- [ ] **Step 15: Ejecutar la suite entera**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 16: Commit**

```bash
git add src/opic/session/state.py src/opic/session/store.py \
        src/opic/session/publish.py src/opic/session/worker.py \
        src/opic/web/app.py src/opic/web/serve.py tests/doubles.py \
        tests/session/test_publish.py tests/session/test_worker.py \
        tests/web/test_feedback_route.py tests/web/conftest.py
git commit -m "feat(session): keep the candidate's verdict, and send it on"
```

---

### Task 7: La tarjeta de feedback en la pantalla final

Cierra §8.1. Sin cambios en la máquina de estados: el examen ya terminó.

**Files:**
- Modify: `src/opic/web/static/steps/done.js` (`renderFrame`, `renderMinimal`,
  `feedbackCard`)
- Modify: `src/opic/web/static/style.css`

**Interfaces:**
- Consumes: `POST /api/sessions/{id}/feedback` de la Task 6.
- Produces: nada que consuma otra tarea.

- [ ] **Step 1: Escribir la tarjeta**

En `src/opic/web/static/steps/done.js`, añadir antes de `restartButton`:

```javascript
// El examen ya terminó, así que esto no es un paso más de la máquina de
// estados: es una tarjeta debajo del informe. Se envía una vez y se sustituye
// por el agradecimiento; un candidato que insista puede recargar, y el
// servidor se limitará a sobrescribir su propia fila pendiente.
function feedbackCard(state, api) {
  const card = document.createElement("form");
  card.className = "feedback";

  const heading = document.createElement("h3");
  heading.textContent = "이 모의고사는 어땠나요?";

  const scale = document.createElement("fieldset");
  const legend = document.createElement("legend");
  legend.textContent = "1점(별로) – 5점(아주 좋음)";
  scale.append(legend);
  for (const value of [1, 2, 3, 4, 5]) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "rating";
    input.value = String(value);
    input.required = true;
    label.append(input, ` ${value}`);
    scale.append(label);
  }

  const commentLabel = document.createElement("label");
  const comment = document.createElement("textarea");
  comment.name = "comment";
  comment.rows = 4;
  comment.maxLength = 2000;
  comment.placeholder = "자유롭게 남겨 주세요. (선택)";
  commentLabel.append("의견 ", comment);

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "보내기";

  const status = document.createElement("p");
  status.className = "issues";

  card.append(heading, scale, commentLabel, submit, status);

  card.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    status.textContent = "";
    const data = new FormData(card);
    try {
      await api.send("POST", `/api/sessions/${state.id}/feedback`, {
        rating: Number(data.get("rating")),
        comment: String(data.get("comment") ?? ""),
      });
      const thanks = document.createElement("p");
      thanks.textContent = "의견 감사합니다.";
      card.replaceChildren(heading, thanks);
    } catch (error) {
      const issues = error.payload?.issues;
      status.textContent = issues?.length
        ? issues.map((issue) => issue.message_ko).join(" ")
        : "의견을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.";
      submit.disabled = false;
    }
  });

  return card;
}
```

- [ ] **Step 2: Colocarla en las dos vistas que muestran un resultado**

`renderFrame` y `renderMinimal` reciben hoy lo justo para dibujar. Pasarles el
estado y la API y añadir la tarjeta al final.

En `load`, las tres llamadas cambian así:

```javascript
  if (page.ready) {
    renderFrame(app, url, page.html, state, api);
    return;
  }
  if (page.html !== null) {
    await waitForWrittenPage(app, url, page.html, state, api);
    return;
  }
  ...
  renderMinimal(app, raw, state, api);
```

En `waitForWrittenPage`, la firma pasa a
`(app, url, provisional, state, api)` y sus dos `renderFrame(...)` internos
pasan `state, api` también.

En `renderFrame`, la firma pasa a `(app, url, html, state, api)` y la última
línea a:

```javascript
  app.replaceChildren(frame, actions, feedbackCard(state, api));
```

En `renderMinimal`, la firma pasa a `(app, raw, state, api)` y el
`replaceChildren` final gana la tarjeta:

```javascript
  app.replaceChildren(
    level,
    based,
    caveat,
    missing,
    dimensions,
    rawDetailsFor(raw),
    feedbackCard(state, api),
    restartButton(),
  );
```

> `renderRetry` no la lleva: si no se pudo cargar ni el informe ni el
> resultado, pedir una valoración del examen es pedirla a ciegas.

- [ ] **Step 3: Un poco de estilo**

En `src/opic/web/static/style.css`, al final:

```css
/* La tarjeta va después del informe, y tiene que leerse como algo aparte de
   él: el informe es el documento que el candidato se lleva; esto es una
   pregunta nuestra. */
.feedback {
  margin-top: 2rem;
  padding-top: 1.5rem;
  border-top: 1px solid currentColor;
  display: grid;
  gap: 0.75rem;
}

.feedback fieldset {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.feedback textarea {
  width: 100%;
}
```

- [ ] **Step 4: Comprobarlo en el navegador**

Run: `uv run pytest -q` (nada debería haberse roto: no hay pruebas de JS)

Después, con una sesión ya graduada en `data/sessions`:

```bash
uv run python -m opic.cli --serve
```

Abrir `http://localhost:8000`, poner en la consola del navegador
`localStorage.setItem("opic.session", "<id de una sesión graduada>")` y
recargar. Comprobar:
1. La tarjeta aparece debajo del informe.
2. Enviar sin elegir puntuación no hace nada (el `required` del radio).
3. Enviada, la tarjeta se sustituye por el agradecimiento.
4. `data/sessions/<id>/session.json` tiene el bloque `feedback`.
5. Sin `OPIC_SHEET_URL`, `published` pasa igualmente a `true` — el sumidero
   nulo cuenta como enviado, que es lo correcto: no hay hoja a la que llegar.

Ctrl-C al terminar.

- [ ] **Step 5: Commit**

```bash
git add src/opic/web/static/steps/done.js src/opic/web/static/style.css
git commit -m "feat(web): ask the candidate what they thought"
```

---

### Task 8: Reenviar una fila a mano

Cierra §8.5.

**Files:**
- Modify: `src/opic/cli.py` (`publish_session`, `main`)
- Create: `tests/test_cli_publish.py`

**Interfaces:**
- Consumes: `sheet_row` (Task 6), `make_sheet_sink` (Task 5).
- Produces: `cli.publish_session(root: Path, session_id: str, sink=None, public_url: str | None = None, out=print) -> int`
  — 0 si la fila salió, 1 si no había feedback o falló el envío.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_cli_publish.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from opic.cli import publish_session
from opic.core.candidate import Candidate
from opic.session import store
from opic.session.state import Feedback

from doubles import ExplodingSheet, FakeSheet


def a_session_with_feedback(root: Path, published: bool = False) -> str:
    state = store.create(root, seed=1, now=datetime(2026, 8, 31, 14, 30, 52))
    state = state.with_candidate(Candidate("김민준", "minjun@example.com"))
    store.save(root, state.with_feedback(Feedback(5, "좋았습니다", published=published)))
    return state.id


def test_it_sends_the_row_and_marks_it(tmp_path: Path):
    session_id = a_session_with_feedback(tmp_path)
    sheet = FakeSheet()
    assert publish_session(tmp_path, session_id, sink=sheet, public_url="", out=lambda _: None) == 0
    assert sheet.rows[0]["email"] == "minjun@example.com"
    assert store.load(tmp_path, session_id).feedback.published is True


def test_it_resends_one_that_was_already_published(tmp_path: Path):
    session_id = a_session_with_feedback(tmp_path, published=True)
    sheet = FakeSheet()
    assert publish_session(tmp_path, session_id, sink=sheet, public_url="", out=lambda _: None) == 0
    assert len(sheet.rows) == 1


def test_no_feedback_is_reported_not_sent(tmp_path: Path):
    state = store.create(tmp_path, seed=1, now=datetime(2026, 8, 31, 14, 30, 52))
    sheet = FakeSheet()
    assert publish_session(tmp_path, state.id, sink=sheet, public_url="", out=lambda _: None) == 1
    assert sheet.rows == []


def test_a_sheet_that_is_down_reports_a_failure(tmp_path: Path):
    session_id = a_session_with_feedback(tmp_path)
    assert (
        publish_session(tmp_path, session_id, sink=ExplodingSheet(), public_url="", out=lambda _: None)
        == 1
    )
    assert store.load(tmp_path, session_id).feedback.published is False


def test_an_unknown_session_reports_a_failure(tmp_path: Path):
    assert publish_session(tmp_path, "nope", sink=FakeSheet(), public_url="", out=lambda _: None) == 1
```

> `--publish` reenvía a propósito una fila ya publicada: existe justamente para
> el caso en que la fila se perdió del otro lado y nadie más puede saberlo.

- [ ] **Step 2: Ejecutar y ver que falla**

Run: `uv run pytest tests/test_cli_publish.py -v`
Expected: FAIL — `cannot import name 'publish_session'`.

- [ ] **Step 3: Implementarlo**

En `src/opic/cli.py`, junto a `find_sessions`:

```python
def publish_session(
    root: Path,
    session_id: str,
    sink=None,
    public_url: str | None = None,
    out=print,
) -> int:
    """Mandar a la hoja la fila de un examen, otra vez si hace falta.

    Sirve para un examen anterior a que esto existiera y para uno cuyo envío
    agotó los reintentos del worker. Reenvía aunque ya conste publicado: si la
    fila se perdió del otro lado, nada de este lado puede enterarse.
    """
    from opic.adapters.sheets import make_sheet_sink
    from opic.session.publish import sheet_row

    sink = sink if sink is not None else make_sheet_sink()
    base = public_url if public_url is not None else os.environ.get("OPIC_PUBLIC_URL", "").strip()

    try:
        state = store.load(root, session_id)
    except (FileNotFoundError, OSError, ValueError, KeyError) as error:
        out(f"error: {error}")
        return 1
    if state.feedback is None:
        out(f"{session_id}: sin feedback que publicar")
        return 1

    result = None
    path = store.result_path(root, session_id)
    if path.exists():
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = None

    try:
        sink.append(sheet_row(state, result, base))
    except Exception as error:  # noqa: BLE001 - lo que falle, se informa igual
        out(f"error: la hoja no aceptó la fila: {error}")
        return 1

    store.save(root, state.with_feedback(replace(state.feedback, published=True)))
    out(f"{session_id}: publicado")
    return 0
```

Añadir a los imports de `cli.py` lo que falte: `os`, y `from dataclasses import replace`.

- [ ] **Step 4: Engancharlo**

En `main`, junto a `--find`:

```python
    parser.add_argument(
        "--publish",
        metavar="SESSION_ID",
        help="send this session's row to the sheet again, and exit",
    )
```

Y el despacho, junto al de `--find`:

```python
    if args.publish is not None:
        return publish_session(args.sessions_root, args.publish)
```

- [ ] **Step 5: Ejecutar las pruebas**

Run: `uv run pytest tests/test_cli_publish.py tests/test_cli.py tests/test_cli_find.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/opic/cli.py tests/test_cli_publish.py
git commit -m "feat(cli): --publish, for the row that never made it"
```

---

### Task 9: `/healthz` y las barandillas

Cierra §7.3 y §7.4. Va antes del despliegue: exponer algo 24/7 sin esto es
peor que no exponerlo.

**Files:**
- Modify: `src/opic/session/worker.py` (`alive`)
- Modify: `src/opic/web/app.py` (gate, `healthz`, `_RateLimiter`,
  `create_session`, `post_answer`)
- Create: `tests/web/test_healthz.py`
- Create: `tests/web/test_guardrails.py`

**Interfaces:**
- Consumes: todo lo anterior.
- Produces:
  - `Worker.alive -> bool` — `True` mientras el hilo no haya muerto; también
    `True` si nunca se arrancó (la CLI y las pruebas manejan el worker a mano).
  - `GET /healthz` — `200 {"status": "ok"}` o `503 {"status": "worker down"}`,
    **fuera de la puerta**.
  - `create_app(..., max_answer_bytes: int = 40 * 1024 * 1024, creates_per_hour: int = 20)`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/web/test_healthz.py`:

```python
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from opic.web.app import create_app


def test_it_answers_ok(client: TestClient):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_it_answers_without_the_share_token(sessions_root, worker):
    """Un vigilante externo no tiene el token, y no debe necesitarlo."""
    app = create_app(root=sessions_root, worker=worker, share_token="s3cret")
    guarded = TestClient(app)
    assert guarded.get("/").status_code == 404
    assert guarded.get("/healthz").status_code == 200


def test_it_says_nothing_else(client: TestClient):
    assert set(client.get("/healthz").json()) == {"status"}


def test_a_dead_worker_is_a_503(sessions_root, worker):
    class DeadWorker:
        alive = False

        def update(self, *args, **kwargs):
            raise AssertionError("not reached")

    app = create_app(root=sessions_root, worker=DeadWorker())
    assert TestClient(app).get("/healthz").status_code == 503
```

Crear `tests/web/test_guardrails.py`:

```python
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from opic.web.app import create_app


def test_an_oversized_answer_is_refused(sessions_root, worker, session_id, client):
    big = b"0" * (2 * 1024 * 1024)
    small_app = create_app(
        root=sessions_root, worker=worker, max_answer_bytes=1024 * 1024,
        clock=lambda: datetime(2026, 8, 31, 14, 0, 0),
    )
    lean = TestClient(small_app)
    response = lean.post(
        f"/api/sessions/{session_id}/answers/0",
        files={"audio": ("answer.webm", big, "audio/webm")},
    )
    assert response.status_code == 413


def test_creating_too_many_sessions_is_refused(sessions_root, worker):
    app = create_app(
        root=sessions_root, worker=worker, creates_per_hour=3,
        clock=lambda: datetime(2026, 8, 31, 14, 0, 0),
    )
    client = TestClient(app)
    for _ in range(3):
        assert client.post("/api/sessions").status_code == 201
    assert client.post("/api/sessions").status_code == 429


def test_the_window_moves(sessions_root, worker):
    now = [datetime(2026, 8, 31, 14, 0, 0)]
    app = create_app(
        root=sessions_root, worker=worker, creates_per_hour=1, clock=lambda: now[0]
    )
    client = TestClient(app)
    assert client.post("/api/sessions").status_code == 201
    assert client.post("/api/sessions").status_code == 429
    now[0] = datetime(2026, 8, 31, 15, 30, 0)
    assert client.post("/api/sessions").status_code == 201
```

- [ ] **Step 2: Ejecutar y ver que fallan**

Run: `uv run pytest tests/web/test_healthz.py tests/web/test_guardrails.py -v`
Expected: FAIL — 404 en `/healthz`, y `create_app` sin esos parámetros.

- [ ] **Step 3: Saber si el worker sigue vivo**

En `src/opic/session/worker.py`, junto a `start`/`stop`:

```python
    @property
    def alive(self) -> bool:
        """Si el hilo, habiendo arrancado, sigue en pie.

        Un worker que nunca se arrancó cuenta como vivo: la CLI y las pruebas
        conducen la cola con `drain()` y no tienen hilo. Lo que esto detecta es
        el fallo silencioso que sí importa en el servidor — el hilo murió y
        FastAPI sigue contestando, así que el candidato hace el examen entero y
        no se transcribe nada.
        """
        return self._thread is None or self._thread.is_alive()
```

- [ ] **Step 4: `/healthz`, y la puerta que lo deja pasar**

En `_install_share_gate`, primera línea del middleware:

```python
    @app.middleware("http")
    async def gate(request, call_next):
        # El chequeo de salud queda fuera del secreto a propósito: un vigilante
        # externo no tiene el token, y lo único que aprende es `ok`.
        if request.url.path == "/healthz":
            return await call_next(request)
        if secrets.compare_digest(request.cookies.get(SHARE_COOKIE, ""), token):
            ...
```

Y la ruta, justo después de `index`:

```python
    @app.get("/healthz")
    def healthz():
        if not worker.alive:
            return JSONResponse(status_code=503, content={"status": "worker down"})
        return {"status": "ok"}
```

- [ ] **Step 5: El límite de tamaño**

En `create_app`, dos parámetros nuevos:

```python
def create_app(
    root: Path,
    worker: Worker,
    clock: Callable[[], datetime] = datetime.now,
    share_token: str | None = None,
    # Unos diez minutos de Opus a 64 kbps. Una respuesta de OPIc dura minuto y
    # medio; esto es holgura, no un objetivo.
    max_answer_bytes: int = 40 * 1024 * 1024,
    creates_per_hour: int = 20,
) -> FastAPI:
```

Junto a `_safe_audio_suffix`, a nivel de módulo:

```python
async def _read_capped(upload: UploadFile, limit: int) -> bytes | None:
    """Leer la subida sin dejar que su tamaño lo decida el cliente.

    `await upload.read()` a secas se traga lo que llegue, y con una sola cola un
    fichero enorme la bloquea entera. `None` significa que se pasó.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)
```

En `post_answer`, sustituir `temporary.write_bytes(await audio.read())` por:

```python
        body = await _read_capped(audio, max_answer_bytes)
        if body is None:
            raise HTTPException(
                status_code=413,
                detail={
                    "detail": f"the answer is larger than {max_answer_bytes} bytes",
                    "reason": "answer_too_large",
                },
            )
        temporary.write_bytes(body)
```

> El `temporary` se crea antes de esta línea; comprobar que la comprobación
> queda **antes** del `write_bytes` y que no deja ficheros `.part` sueltos.
> Si el orden actual lo obliga, mover la creación del nombre temporal después
> de la lectura.

- [ ] **Step 6: El límite de creación**

A nivel de módulo en `app.py`:

```python
class _RateLimiter:
    """Cuántas veces se ha hecho algo por origen, en una ventana móvil.

    En memoria y por proceso: hay un solo proceso por diseño (`serve.py`), y
    reiniciar el servidor perdona a todo el mundo, que es aceptable para lo que
    esto defiende — que un enlace filtrado no genere mil exámenes a tu cuenta
    de Anthropic mientras duermes.
    """

    def __init__(self, limit: int, window: timedelta, clock: Callable[[], datetime]) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._seen: dict[str, list[datetime]] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        cutoff = now - self._window
        recent = [when for when in self._seen.get(key, []) if when > cutoff]
        if len(recent) >= self._limit:
            self._seen[key] = recent
            return False
        recent.append(now)
        self._seen[key] = recent
        return True


def _caller(request: Request) -> str:
    """Quién pregunta, visto desde detrás del túnel.

    cloudflared habla con este proceso desde 127.0.0.1, así que sin la cabecera
    todos los invitados serían el mismo origen. `cf-connecting-ip` es fiable
    aquí sólo porque el puerto no es alcanzable de otra forma: la pone
    Cloudflare y nadie más llega a este proceso.
    """
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
```

Importar lo que falte: `from datetime import datetime, timedelta` y `Request`
de `fastapi`.

Dentro de `create_app`, antes de las rutas:

```python
    creations = _RateLimiter(creates_per_hour, timedelta(hours=1), clock)
```

Y `create_session` pasa a:

```python
    @app.post("/api/sessions", status_code=201)
    def create_session(request: Request) -> dict:
        if not creations.allow(_caller(request)):
            raise HTTPException(
                status_code=429,
                detail={
                    "detail": "too many sessions from this address",
                    "reason": "too_many_sessions",
                },
            )
        state = store.create(root, seed=int(clock().timestamp()), now=clock())
        return session_json(state)
```

- [ ] **Step 7: Ejecutar las pruebas nuevas**

Run: `uv run pytest tests/web/test_healthz.py tests/web/test_guardrails.py -v`
Expected: PASS.

- [ ] **Step 8: Ejecutar la suite entera**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: PASS y sin avisos.

> Si alguna prueba de `tests/web` crea muchas sesiones seguidas y ahora choca
> con el 429, subir `creates_per_hour` en la fixture `client`, no bajar el
> límite por defecto.

- [ ] **Step 9: Commit**

```bash
git add src/opic/session/worker.py src/opic/web/app.py \
        tests/web/test_healthz.py tests/web/test_guardrails.py
git commit -m "feat(web): a health check, a size cap and a rate limit"
```

---

### Task 10: El despliegue permanente

Cierra §7.1, §7.2 y la documentación. Última porque expone todo lo anterior.

**Files:**
- Create: `tools/deploy/com.opic.server.plist.template`
- Create: `tools/deploy/com.opic.tunnel.plist.template`
- Create: `tools/deploy/cloudflared-config.yml.template`
- Create: `tools/deploy/install.sh`
- Create: `docs/deploy.md`
- Modify: `README.md` (una sección corta que apunte a `docs/deploy.md`)
- Modify: `.gitignore` (`tools/deploy/*.local.*`)

**Interfaces:**
- Consumes: `/healthz` de la Task 9, `OPIC_SHEET_URL` y `OPIC_PUBLIC_URL` de
  las Tasks 5 y 6.
- Produces: nada que consuma otra tarea.

- [ ] **Step 1: El fichero del túnel**

Crear `tools/deploy/cloudflared-config.yml.template`:

```yaml
# Copiar a ~/.cloudflared/config.yml y sustituir los marcadores.
# TUNNEL_ID sale de `cloudflared tunnel create opic`.
tunnel: TUNNEL_ID
credentials-file: /Users/USERNAME/.cloudflared/TUNNEL_ID.json

ingress:
  - hostname: HOSTNAME
    service: http://localhost:8000
  # Cloudflare exige una regla final que lo recoja todo.
  - service: http_status:404
```

- [ ] **Step 2: Los dos agentes**

Crear `tools/deploy/com.opic.server.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.opic.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <!-- El entorno de un agente de launchd no es el de tu terminal: no hay
         `.env` cargado, ni PATH de Homebrew, ni uv. Por eso el `source` y la
         ruta absoluta. -->
    <string>set -a; source REPO/.env.deploy; set +a; cd REPO &amp;&amp; UV --directory REPO run uvicorn --factory opic.web.serve:app --host 127.0.0.1 --port 8000</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>REPO/data/logs/server.log</string>
  <key>StandardErrorPath</key>
  <string>REPO/data/logs/server.err.log</string>
</dict>
</plist>
```

Crear `tools/deploy/com.opic.tunnel.plist.template`, idéntico salvo:

```xml
  <key>Label</key>
  <string>com.opic.tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>CLOUDFLARED</string>
    <string>tunnel</string>
    <string>run</string>
    <string>opic</string>
  </array>
  ...
  <key>StandardOutPath</key>
  <string>REPO/data/logs/tunnel.log</string>
  <key>StandardErrorPath</key>
  <string>REPO/data/logs/tunnel.err.log</string>
```

- [ ] **Step 3: El instalador**

Crear `tools/deploy/install.sh`, con el mismo tono defensivo que
`tools/share.sh`:

```bash
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
```

- [ ] **Step 4: Hacerlo ejecutable y comprobar la sintaxis**

Run:
```bash
chmod +x tools/deploy/install.sh
bash -n tools/deploy/install.sh && echo "sintaxis ok"
```
Expected: `sintaxis ok`.

- [ ] **Step 5: La documentación**

Crear `docs/deploy.md`:

````markdown
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
````

- [ ] **Step 6: `.gitignore` y `README.md`**

Añadir a `.gitignore`:

```
.env.deploy
```

Y en `README.md`, después de la sección de `--serve`, un párrafo corto:

```markdown
### En pie sin nadie delante

`tools/share.sh` sirve para un examen suelto: túnel efímero, enlace nuevo cada
vez. Para dejarlo disponible de forma permanente —dominio propio, dos agentes
de `launchd`, hoja de cálculo con las valoraciones— está `docs/deploy.md`, que
también explica qué se pierde en seguridad al hacerlo.
```

- [ ] **Step 7: Comprobar que la suite sigue verde**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tools/deploy docs/deploy.md README.md .gitignore
git commit -m "feat(deploy): a named tunnel and two launchd agents"
```

- [ ] **Step 9: La prueba de verdad**

Esto no se puede automatizar y no se debe saltar. Con el despliegue hecho:

1. Desde **otro dispositivo, con datos móviles** (no tu wifi), abrir el enlace.
2. Hacer un examen entero de cinco preguntas.
3. Comprobar que el informe aparece.
4. Enviar el feedback y comprobar que la fila llega a la hoja.
5. `uv run python -m opic.cli --find <el correo que pusiste>` la encuentra.
6. Reiniciar el Mac y comprobar que el enlace vuelve solo, sin tocar nada.

El paso 6 es el que dice si esto cumple lo que promete.

---

## Self-review

**Cobertura del diseño:**

| Sección del diseño | Tarea |
|---|---|
| §4.1 paso nuevo | Task 2 |
| §4.2 datos del candidato | Task 2 |
| §4.3 endpoint | Task 3 |
| §4.4 pantalla | Task 3 |
| §5 ids y `created_at` | Task 1 |
| §6 la hoja como índice | Task 6 (fila) |
| §6 la consola | Task 4 |
| §7.1 túnel con nombre | Task 10 |
| §7.2 launchd | Task 10 |
| §7.3 `/healthz` | Task 9 |
| §7.4 barandillas | Task 9 (código), Task 10 (documentación y límite de gasto) |
| §8.1 dónde vive la tarjeta | Task 7 |
| §8.2 disco antes que Google | Task 6 |
| §8.3 puerto y adaptador | Task 5 |
| §8.4 la fila | Task 6 |
| §8.5 reintento manual | Task 8 |
| §9 pruebas | Repartidas; la de compatibilidad es el Step 8 de la Task 1 |

Sin huecos.

**Consistencia de nombres:** `new_session_id()` sin argumentos desde la Task 1 y
así se usa en la Task 2. `SessionState.new(session_id, seed, created_at)` con
tres argumentos en las Tasks 1, 2, 4, 6 y 8. `sheet_row(state, result,
public_url)` se define en la Task 6 y se reutiliza en la Task 8. `Feedback`
lleva `published` con valor por defecto `False` en todas. `Worker.alive` es
propiedad, no método, en la Task 9 y en la ruta que la consume.
