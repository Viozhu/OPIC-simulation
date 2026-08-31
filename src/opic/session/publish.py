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
