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
