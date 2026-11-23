"""Normalización de textos y de días de visita."""

from __future__ import annotations

import re
import unicodedata

DIAS_SEMANA = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}

_NO_ALFANUMERICO = re.compile(r"[^0-9a-z]+")


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin tildes ni diacríticos, sin signos y con espacios simples."""
    descompuesto = unicodedata.normalize("NFKD", texto.casefold())
    sin_marcas = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return _NO_ALFANUMERICO.sub(" ", sin_marcas).strip()


def parsear_dias_visita(texto: str) -> frozenset[int]:
    """'lunes, Jueves' -> {0, 3}. Lanza ValueError con el token desconocido."""
    dias: set[int] = set()
    for token in texto.split(","):
        normalizado = normalizar_texto(token)
        if not normalizado:
            continue
        if normalizado not in DIAS_SEMANA:
            raise ValueError(f"día de visita desconocido: {normalizado!r}")
        dias.add(DIAS_SEMANA[normalizado])
    return frozenset(dias)
