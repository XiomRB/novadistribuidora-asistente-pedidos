from __future__ import annotations

import pytest

from app.datos.carga import cargar_datos
from app.datos.modelos import Datos
from tests.fixtures import datos_sinteticos


@pytest.fixture
def dir_sintetico(tmp_path):
    return datos_sinteticos.escribir(tmp_path / "datos")


@pytest.fixture
def datos(dir_sintetico) -> Datos:
    return cargar_datos(dir_sintetico)
