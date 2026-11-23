"""Pruebas de referencia con datos reales locales.

- DATA_DIR: carpeta con los parquet reales (por defecto ./datos).
- EVAL_DEV_PATH: ruta al archivo de casos de desarrollo publicado (sin valor por defecto).

Si falta alguno, las pruebas se omiten con el motivo. Los datos y los casos nunca se versionan.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from app.datos.carga import COLUMNAS, cargar_datos

RAIZ = Path(__file__).resolve().parents[2]


def pytest_collection_modifyitems(items):
    for item in items:
        if Path(str(item.fspath)).parent == Path(__file__).parent:
            item.add_marker(pytest.mark.referencia)


@pytest.fixture(scope="session")
def ruta_datos_reales() -> Path:
    ruta = Path(os.environ.get("DATA_DIR", RAIZ / "datos"))
    faltantes = [n for n in COLUMNAS if not (ruta / f"{n}.parquet").is_file()]
    if faltantes:
        pytest.skip(f"Datos reales no disponibles en {ruta} (faltan: {', '.join(faltantes)}); definir DATA_DIR")
    return ruta


@pytest.fixture(scope="session")
def datos_reales(ruta_datos_reales):
    return cargar_datos(ruta_datos_reales)


@pytest.fixture(scope="session")
def ruta_casos_dev() -> Path:
    valor = os.environ.get("EVAL_DEV_PATH")
    if not valor:
        pytest.skip("EVAL_DEV_PATH no definido: se omiten las pruebas con los casos de desarrollo")
    ruta = Path(valor)
    if not ruta.is_file():
        pytest.skip(f"EVAL_DEV_PATH no apunta a un archivo existente: {ruta}")
    return ruta


@pytest.fixture(scope="session")
def lineas_crudas_dev(ruta_casos_dev) -> list[str]:
    return [l for l in ruta_casos_dev.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture(scope="session")
def casos_dev(lineas_crudas_dev) -> list[dict]:
    return [json.loads(l, parse_float=Decimal) for l in lineas_crudas_dev]
