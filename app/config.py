"""Configuración de la API, leída de variables de entorno.

- `DATA_DIR`: carpeta con los cinco archivos `.parquet` (por defecto `./datos`). Si faltan o son
  inválidos, la API no arranca (D24).
- Intérprete (hito 1): `OPENROUTER_API_KEY`, `LLM_MODELO`, `LLM_TIMEOUT_S` (segundos enteros, por
  defecto 30, de 1 a 120), `LLM_REINTENTOS` (por defecto 1, de 0 a 2) y `LLM_INSTRUCCIONES` (`base` o `catalogo`).
  Sin clave o sin modelo, el intérprete queda no configurado (503 y `/health` degradado).
  La clave nunca aparece en `repr` ni en mensajes de error.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DIR_DATOS_POR_DEFECTO = "datos"
TIMEOUT_POR_DEFECTO_S = 30
REINTENTOS_POR_DEFECTO = 1
MAX_REINTENTOS = 2
INSTRUCCIONES_POR_DEFECTO = "base"


class ConfiguracionInvalida(ValueError):
    """Un valor de configuración no es válido. El mensaje solo nombra la variable."""


def _entero(entorno: Mapping[str, str], nombre: str, por_defecto: int, minimo: int, maximo: int) -> int:
    texto = (entorno.get(nombre) or "").strip()
    if not texto:
        return por_defecto
    if not texto.isdigit():
        raise ConfiguracionInvalida(f"{nombre} debe ser un entero")
    valor = int(texto)
    if not minimo <= valor <= maximo:
        raise ConfiguracionInvalida(f"{nombre} debe estar entre {minimo} y {maximo}")
    return valor


@dataclass(frozen=True)
class Configuracion:
    dir_datos: Path
    openrouter_api_key: str = field(default="", repr=False)
    llm_modelo: str = ""
    llm_timeout_s: int = TIMEOUT_POR_DEFECTO_S
    llm_reintentos: int = REINTENTOS_POR_DEFECTO
    llm_instrucciones: str = INSTRUCCIONES_POR_DEFECTO

    @property
    def interprete_configurado(self) -> bool:
        return bool(self.openrouter_api_key and self.llm_modelo)

    @classmethod
    def desde_entorno(cls, entorno: Mapping[str, str] | None = None) -> Configuracion:
        entorno = os.environ if entorno is None else entorno
        instrucciones = (entorno.get("LLM_INSTRUCCIONES") or INSTRUCCIONES_POR_DEFECTO).strip()
        if instrucciones not in ("base", "catalogo"):
            raise ConfiguracionInvalida("LLM_INSTRUCCIONES debe ser 'base' o 'catalogo'")
        return cls(
            dir_datos=Path(entorno.get("DATA_DIR") or DIR_DATOS_POR_DEFECTO),
            openrouter_api_key=(entorno.get("OPENROUTER_API_KEY") or "").strip(),
            llm_modelo=(entorno.get("LLM_MODELO") or "").strip(),
            llm_timeout_s=_entero(entorno, "LLM_TIMEOUT_S", TIMEOUT_POR_DEFECTO_S, 1, 120),
            llm_reintentos=_entero(entorno, "LLM_REINTENTOS", REINTENTOS_POR_DEFECTO, 0, MAX_REINTENTOS),
            llm_instrucciones=instrucciones,
        )
