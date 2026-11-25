"""D92: los códigos internos de la resolución (`CANDIDATOS_LLM_IGNORADOS`, `SIN_ANCLA_CATALOGO`,
`TOKEN_DESCONOCIDO`) se quedan en `Resolucion.codigos`. No llegan al diagnóstico (solo pasan los
de `CODIGOS_DESACUERDO` de `plegado.py`, sin cambios), ni a la respuesta HTTP, ni a los logs."""

import dataclasses
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.dominio.plegado import CODIGOS_DESACUERDO
from app.main import crear_app
from tests.fixtures.api_e2b import RUTA, solicitud
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.interprete_falso import InterpreteFijo
from tests.fixtures.pedido_e1b2b import cargar_recursos, pendientes, procesar

INTERNOS = ("CANDIDATOS_LLM_IGNORADOS", "SIN_ANCLA_CATALOGO", "TOKEN_DESCONOCIDO")
MENSAJE = "2 de levadura en polvo"
EVENTO = ev(1, 0, "agregar", MENSAJE, producto="levadura en polvo", cantidad="2", candidatos=["LP3"])


@pytest.fixture(scope="module")
def contexto_y_recursos(tmp_path_factory):
    return cargar_recursos(tmp_path_factory.mktemp("r_e3_09_internos"))


def test_la_resolucion_si_registra_el_codigo(contexto_y_recursos):
    ctx, _ = contexto_y_recursos
    assert "CANDIDATOS_LLM_IGNORADOS" in ctx.indice.resolver("levadura en polvo", ["LP3"]).codigos


def test_el_codigo_no_llega_al_diagnostico(contexto_y_recursos):
    _, rec = contexto_y_recursos
    r = procesar(rec, [MENSAJE], [EVENTO])
    assert pendientes(r) == [("producto_no_existe", "levadura en polvo", ())]
    diagnostico = json.dumps(dataclasses.asdict(r.diagnostico), default=str)
    assert not [c for c in INTERNOS if c in diagnostico]
    assert all(d.codigo in CODIGOS_DESACUERDO for d in r.diagnostico.desacuerdos)


def test_el_codigo_no_llega_a_la_respuesta_http_ni_a_los_logs(contexto_y_recursos, caplog):
    ctx, _ = contexto_y_recursos
    caplog.set_level(logging.DEBUG)
    with TestClient(crear_app(datos=ctx.datos, interprete=InterpreteFijo({"eventos": [EVENTO]}))) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud([MENSAJE]))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert [p["motivo"] for p in cuerpo["pendientes"]] == ["producto_no_existe"] and cuerpo["lineas"] == []
    assert not [c for c in INTERNOS if c in respuesta.text or c in str(dict(respuesta.headers))]
    assert not [c for c in INTERNOS if c in caplog.text]
