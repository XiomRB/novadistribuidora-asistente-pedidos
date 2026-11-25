"""D93 por el orquestador, con el catálogo sintético (ejemplos sintéticos, sin datos reales).

- Escenarios de la matriz con varios eventos (7, 8, 9, 45) y los que cambian el resultado.
- Cuando D93 no se activa, el pedido es idéntico al que se obtiene con D93 desactivado.
- Las llamadas a la resolución sin dimensión son exactamente las de antes.
- DIMENSION_CANTIDAD_INCOMPATIBLE es interno: no llega al diagnóstico, a la respuesta HTTP, a los
  encabezados ni a los logs (caso 24).
"""

import dataclasses
import json
import logging

import pytest
from fastapi.testclient import TestClient

import app.dominio.plegado as plegado
from app.dominio.catalogo import CODIGO_DIMENSION
from app.main import crear_app
from tests.fixtures.api_e2b import RUTA, solicitud
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.interprete_falso import InterpreteFijo
from tests.fixtures.pedido_e1b2b import cargar_recursos, lineas, pendientes, procesar

X = "detergente espuma"  # se vende por peso (500 g)
NE, AM, CN = "producto_no_existe", "producto_ambiguo", "cantidad_no_convertible"


@pytest.fixture(scope="module")
def contexto_y_recursos(tmp_path_factory):
    return cargar_recursos(tmp_path_factory.mktemp("d93"))


@pytest.fixture
def rec(contexto_y_recursos):
    return contexto_y_recursos[1]


def litros(i, m, texto, cantidad="5", producto=X, unidad_texto="litros"):
    return ev(i, m, "agregar", texto, producto=producto, cantidad=cantidad, unidad="otra", unidad_texto=unidad_texto)


def resultado(r):
    return lineas(r), [(m, o) for m, _, o in pendientes(r)]


def sin_d93(monkeypatch):
    monkeypatch.setattr(plegado, "dimension_cantidad_total", lambda *_: None)


# (caso, mensajes, eventos, resultado con D93, resultado sin D93)
CAMBIAN = [
    ("c6", [f"5 litros de {X}"], [litros(1, 0, f"5 litros de {X}")], ([], [(NE, ())]), ([], [(CN, ("DT5",))])),
    (
        "c7", [f"5 litros de {X}", "mejor detergente Brillante"],
        [litros(1, 0, f"5 litros de {X}"), ev(2, 1, "precisar", "detergente Brillante", producto="detergente Brillante", ref="e1")],
        ([], [(NE, ())]), ([], [(CN, ("DT5",))]),
    ),
    (
        "c8", [f"5 litros de {X}", "mejor 3 cajas"],  # decisión A (D63: no se vuelve a resolver)
        [litros(1, 0, f"5 litros de {X}"), ev(2, 1, "corregir", "mejor 3 cajas", cantidad="3", unidad="venta", unidad_texto="cajas", ref="e1")],
        ([], [(NE, ())]), ([], [(CN, ("DT5",))]),
    ),
    (
        "c45", [f"5 de {X}", "que sean 5 litros", "mejor detergente Brillante"],
        # La corrección (Q2) registra la dimensión; el `precisar` vuelve a resolver (D69) con esa cantidad.
        [ev(1, 0, "agregar", f"5 de {X}", producto=X, cantidad="5"),
         ev(2, 1, "corregir", "que sean 5 litros", cantidad="5", unidad="otra", unidad_texto="litros", ref="e1"),
         ev(3, 2, "precisar", "detergente Brillante", producto="detergente Brillante", ref="e1")],
        ([], [(NE, ())]), ([], [(CN, ("DT5",))]),
    ),
    ("c13", [f"2 litros de {X}"], [litros(1, 0, f"2 litros de {X}", cantidad="2")], ([], [(NE, ())]), ([], [(CN, ("DT5",))])),
    (
        "c14", ["6 libras de cloro claro"],
        [ev(1, 0, "agregar", "6 libras de cloro claro", producto="cloro claro", cantidad="6", unidad="otra", unidad_texto="libras")],
        ([], [(NE, ())]), ([], [(CN, ("CL1",))]),
    ),
    (
        "c15", ["2 libras de pasta"],  # filtro parcial: se descarta la pasta dental
        [ev(1, 0, "agregar", "2 libras de pasta", producto="pasta", cantidad="2", unidad="otra", unidad_texto="libras")],
        ([], [(AM, ("PC2", "PE2"))]), ([], [(AM, ("PC2", "PE2", "PD7"))]),
    ),
    (
        "c15-una-opcion", ["1 litro de pasta"],  # queda una sola opción y sigue ambiguo (nunca se confirma)
        [ev(1, 0, "agregar", "1 litro de pasta", producto="pasta", cantidad="1", unidad="otra", unidad_texto="litro")],
        ([], [(AM, ("PD7",))]), ([], [(AM, ("PC2", "PE2", "PD7"))]),
    ),
    (
        "R2-extendida", ["5 litros de detergente Brillante"],  # ancla + token desconocido + dimensión incompatible
        [litros(1, 0, "5 litros de detergente Brillante", producto="detergente Brillante")],
        ([], [(NE, ())]), ([], [(AM, ())]),
    ),
]


@pytest.mark.parametrize(("caso", "mensajes", "eventos", "con", "sin"), CAMBIAN, ids=[c[0] for c in CAMBIAN])
def test_escenarios_que_d93_cambia(rec, monkeypatch, caso, mensajes, eventos, con, sin):
    assert resultado(procesar(rec, mensajes, eventos)) == con
    sin_d93(monkeypatch)
    assert resultado(procesar(rec, mensajes, eventos)) == sin


# (caso, mensajes, eventos, resultado esperado): D93 no se activa o no cambia nada.
IGUALES = [
    ("c1", [f"2 cajas de {X} de 1 litro"],
     [ev(1, 0, "agregar", f"2 cajas de {X} de 1 litro", producto=X, cantidad="2", unidad="venta", unidad_texto="cajas", presentacion="1 litro")],
     ([], [(NE, ())])),
    ("c2", [f"2 cajas de {X} de 1 litro"], [litros(1, 0, f"2 cajas de {X} de 1 litro", cantidad="1", unidad_texto="litro")], ([], [(CN, ("DT5",))])),
    ("c4", [f"6 bolsitas de {X} de medio litro"],
     [ev(1, 0, "agregar", f"6 bolsitas de {X} de medio litro", producto=X, cantidad="6", unidad="suelta", unidad_texto="bolsitas", presentacion="medio litro")],
     ([], [(NE, ())])),
    ("c9", [f"2 cajas de {X}", "mejor 5 litros"],  # decisión B: la línea no se vuelve a resolver
     [ev(1, 0, "agregar", f"2 cajas de {X}", producto=X, cantidad="2", unidad="venta", unidad_texto="cajas"),
      ev(2, 1, "corregir", "mejor 5 litros", cantidad="5", unidad="otra", unidad_texto="litros", ref="e1")],
     ([], [(CN, ("DT5",))])),
    ("c16", ["3 kilos de frijol negro"],
     [ev(1, 0, "agregar", "3 kilos de frijol negro", producto="frijol negro", cantidad="3", unidad="otra", unidad_texto="kilos")],
     ([], [(CN, ("FN1",))])),
    ("c17", ["4 libras de frijol rojo"],
     [ev(1, 0, "agregar", "4 libras de frijol rojo", producto="frijol rojo", cantidad="4", unidad="otra", unidad_texto="libras")],
     ([], [(CN, ("FR1",))])),
    ("c19", [f"4 cajas de {X}", "6 bolsitas de medio litro"],
     [ev(1, 0, "agregar", f"4 cajas de {X}", producto=X, cantidad="4", unidad="venta", unidad_texto="cajas"),
      ev(2, 1, "corregir", "6 bolsitas de medio litro", presentacion="medio litro", cantidad="6", unidad="suelta", unidad_texto="bolsitas", ref="e1")],
     ([], [(NE, ())])),
    ("c20", [f"5 litros de {X}"], [ev(1, 0, "agregar", f"5 litros de {X}", producto=X, presentacion="5 litros")], ([], [(NE, ())])),
    ("c23", [f"5 de {X}"], [litros(1, 0, f"5 de {X}")], ([], [(CN, ("DT5",))])),
    ("c31", [f"{X}, 5 litros"], [litros(1, 0, f"{X}, 5 litros")], ([], [(CN, ("DT5",))])),
    ("c60", [f"5 litros de {X} para todos"], [litros(1, 0, f"5 litros de {X} para todos")], ([], [(CN, ("DT5",))])),
    ("volumen-igual", ["2 litros de gaseosa sol"],
     [ev(1, 0, "agregar", "2 litros de gaseosa sol", producto="gaseosa sol", cantidad="2", unidad="otra", unidad_texto="litros")],
     ([], [(AM, ("GS6", "GS2", "GS3"))])),
    ("sin-dimension", ["3 kilos de galletas luna"],  # productos sin dimensión (paquetes): nunca se descartan
     [ev(1, 0, "agregar", "3 kilos de galletas luna", producto="galletas luna", cantidad="3", unidad="otra", unidad_texto="kilos")],
     ([], [(AM, ("GV1", "GC1"))])),
    ("unidad-comercial", [f"3 fardos de {X}"],  # DT5 se vende por fardo
     [ev(1, 0, "agregar", f"3 fardos de {X}", producto=X, cantidad="3", unidad="venta", unidad_texto="fardos")],
     ([("DT5", "3")], [])),
]


@pytest.mark.parametrize(("caso", "mensajes", "eventos", "esperado"), IGUALES, ids=[c[0] for c in IGUALES])
def test_escenarios_iguales_con_y_sin_d93(rec, monkeypatch, caso, mensajes, eventos, esperado):
    con = procesar(rec, mensajes, eventos)
    sin_d93(monkeypatch)
    sin = procesar(rec, mensajes, eventos)
    assert resultado(con) == resultado(sin) == esperado
    assert con.cierre == sin.cierre


def test_sin_dimension_la_resolucion_se_llama_exactamente_como_antes(rec, monkeypatch):
    llamadas = []
    original = rec.indice.resolver

    def espia(*args, **kwargs):
        llamadas.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(rec.indice, "resolver", espia)
    procesar(rec, [f"3 cajas de {X}", "y 2 de frijol negro"],
             [ev(1, 0, "agregar", f"3 cajas de {X}", producto=X, cantidad="3", unidad="venta", unidad_texto="cajas"),
              ev(2, 1, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2")])
    assert llamadas and all(len(a) == 2 and not k for a, k in llamadas)  # (descripción, candidatos): sin dimensiones
    llamadas.clear()
    procesar(rec, [f"5 litros de {X}"], [litros(1, 0, f"5 litros de {X}")])
    assert any(len(a) == 3 and a[2] == frozenset({"volumen"}) for a, _ in llamadas)


# ---------------------------------------------------------------- caso 24: código interno


def test_la_resolucion_registra_el_codigo(rec):
    r = rec.indice.resolver(X, (), frozenset({"volumen"}))
    assert r.tipo.value == "no_existe" and CODIGO_DIMENSION in r.codigos


def test_el_codigo_no_llega_al_diagnostico(rec):
    r = procesar(rec, [f"5 litros de {X}"], [litros(1, 0, f"5 litros de {X}")])
    assert pendientes(r) == [(NE, X, ())]
    assert CODIGO_DIMENSION not in json.dumps(dataclasses.asdict(r.diagnostico), default=str)


def test_el_codigo_no_llega_a_la_respuesta_http_ni_a_los_encabezados_ni_a_los_logs(contexto_y_recursos, caplog):
    ctx, _ = contexto_y_recursos
    caplog.set_level(logging.DEBUG)
    interprete = InterpreteFijo({"eventos": [litros(1, 0, f"5 litros de {X}")]})
    with TestClient(crear_app(datos=ctx.datos, interprete=interprete)) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud([f"5 litros de {X}"]))
    assert respuesta.status_code == 200
    assert [p["motivo"] for p in respuesta.json()["pendientes"]] == [NE] and respuesta.json()["lineas"] == []
    assert CODIGO_DIMENSION not in respuesta.text and CODIGO_DIMENSION not in str(dict(respuesta.headers))
    assert CODIGO_DIMENSION not in caplog.text
