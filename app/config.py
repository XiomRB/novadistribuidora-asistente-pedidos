"""Configuración de la API (E2b), leída de variables de entorno.

- `DATA_DIR`: carpeta con los cinco archivos `.parquet` (por defecto `./datos`). Si faltan o son
  inválidos, la API no arranca (D24).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DIR_DATOS_POR_DEFECTO = "datos"


@dataclass(frozen=True)
class Configuracion:
    dir_datos: Path

    @classmethod
    def desde_entorno(cls, entorno: Mapping[str, str] | None = None) -> Configuracion:
        entorno = os.environ if entorno is None else entorno
        return cls(dir_datos=Path(entorno.get("DATA_DIR") or DIR_DATOS_POR_DEFECTO))
