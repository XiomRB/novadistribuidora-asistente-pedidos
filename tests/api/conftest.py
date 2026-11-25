"""Fixtures de las pruebas de la API (E2b): datos sintéticos y clientes HTTP de prueba."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.main import crear_app
from tests.fixtures.historial_e1b2 import cargar_contexto


@pytest.fixture(scope="session")
def ctx(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("api"))


@pytest.fixture
def cliente_con(ctx):
    """`with cliente_con(interprete) as cliente:` -> TestClient con el arranque ejecutado."""

    @contextmanager
    def fabrica(interprete=None, sondas=(), **opciones) -> Iterator[TestClient]:
        with TestClient(crear_app(datos=ctx.datos, interprete=interprete, sondas=sondas), **opciones) as cliente:
            yield cliente

    return fabrica

