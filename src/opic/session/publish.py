"""Una sesión, vista como una fila de hoja de cálculo.

Puro: recibe el estado y el `result.json` ya leído, y devuelve un diccionario
de cadenas. Quien lo llama es el que toca el disco y la red.
"""

from __future__ import annotations

from opic.session.state import SessionState

# `name`, `email` y `comment` los escribe un desconocido: el examen entero
# existe para que un extraño lo tome desde un enlace. Google Sheets evalúa
# como fórmula cualquier celda cuyo texto empiece por uno de estos caracteres
# — `=IMPORTXML(...)`, `=HYPERLINK(...)` — así que sin esto un comentario es
# suficiente para que la hoja del dueño salga a pedir una URL que él nunca
# escribió. Anteponer un apóstrofo fuerza la celda a texto sin que el
# apóstrofo llegue a verse: es lo que hace la propia hoja de cálculo cuando
# alguien escribe lo mismo a mano.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _as_text(value: str) -> str:
    """Neutraliza un valor que Sheets interpretaría como fórmula.

    Se aplica a toda columna, no sólo a las que hoy vienen de un formulario:
    una columna futura hereda la protección sin que nadie tenga que acordarse
    de pedirla. Un comentario que legítimamente empieza por `-` (una lista, un
    guion coreano) llega intacto igualmente — sólo cambia cómo lo ve Sheets,
    nunca el texto que se lee.
    """
    return f"'{value}" if value[:1] in _FORMULA_TRIGGERS else value


def _report_url(base: str, state: SessionState) -> str:
    """El enlace que el dueño abrirá desde la hoja, con lo que hace falta para
    que se abra.

    La cookie de la sesión la tiene el candidato, en su navegador y en su
    máquina. El dueño pincha esto desde la hoja, meses después si hace falta, y
    sin la clave de lectura vería el mismo 404 que un desconocido. La clave va
    en la URL porque la URL es lo único que la hoja puede guardar.

    Sin clave — una sesión anterior a que existieran — el enlace se queda como
    era: no hay nada que añadir, y su informe sigue abriéndose sin ella.
    """
    page = f"{base}/api/sessions/{state.id}/page"
    if state.read_key is None:
        return page
    # `token_urlsafe` no produce nada que haya que escapar en una query.
    return f"{page}?r={state.read_key}"


def sheet_row(state: SessionState, result: dict | None, public_url: str) -> dict[str, str]:
    candidate = state.candidate
    feedback = state.feedback
    base = public_url.rstrip("/")
    row = {
        "timestamp": state.created_at.isoformat(),
        "session_id": state.id,
        "name": candidate.name if candidate else "",
        "email": candidate.email if candidate else "",
        "level": str(result.get("final_level", "")) if result else "",
        "rating": str(feedback.rating) if feedback else "",
        "comment": feedback.comment if feedback else "",
        # Sin URL pública no hay enlace que ofrecer: el servidor no puede saber
        # por sí mismo bajo qué nombre lo ven desde fuera.
        "report_url": _report_url(base, state) if base else "",
    }
    return {key: _as_text(value) for key, value in row.items()}
