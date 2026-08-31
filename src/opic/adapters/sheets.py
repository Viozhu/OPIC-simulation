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
import urllib.error
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
        except urllib.error.HTTPError as error:
            raise SheetError(f"the sheet answered {error.code}") from error
        except OSError as error:
            raise SheetError(f"the sheet did not answer: {error}") from error
        if status >= 400:
            raise SheetError(f"the sheet answered {status}")


def make_sheet_sink(url: str | None = None) -> NullSheet | AppsScriptSheet:
    """`OPIC_SHEET_URL` decide, con el mismo patrón que `OPIC_LLM`."""
    resolved = (url if url is not None else os.environ.get("OPIC_SHEET_URL", "")).strip()
    return AppsScriptSheet(resolved) if resolved else NullSheet()
