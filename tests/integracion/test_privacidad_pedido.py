"""Privacidad de extremo a extremo (E1b-2b): ni el diagnóstico ni el mensaje al cliente contienen
texto de los mensajes, texto de los pendientes, nombres ni identificadores; los módulos nuevos no
escriben logs; los errores de límites no incluyen contenido."""

import ast
import logging
from pathlib import Path

import pytest

from app.dominio.limites import LimitesExcedidos
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.pedido_e1b2b import cargar_recursos, frag, procesar

RAIZ = Path(__file__).resolve().parents[2]
MARCAS = ["ZQXPRIV2", "Persona Inventada", "WKNOMBRE", "5555-0101", "correo@ejemplo.invalid"]


@pytest.fixture(scope="module")
def rec(tmp_path_factory):
    return cargar_recursos(tmp_path_factory.mktemp("privacidad_pedido"))[1]


def test_diagnostico_y_mensaje_sin_textos_ni_identificadores(rec, caplog):
    mensajes = [
        "Hola, soy Persona Inventada (WKNOMBRE), mi número es 5555-0101 y mi correo correo@ejemplo.invalid. "
        "Mándeme 2 de aceite ZQXPRIV2, 3 fardos de gaseosa ZQXPRIV2 y lo de siempre",
        "¿tienen frijol ZQXPRIV2? y 5 de cerveza ZQXPRIV2",
    ]
    eventos = [
        ev(1, 0, "agregar", "2 de aceite ZQXPRIV2", producto="aceite ZQXPRIV2", cantidad="2"),
        ev(2, 0, "habitual", "lo de siempre"),
        ev(3, 1, "agregar", "frijol ZQXPRIV2", producto="frijol ZQXPRIV2"),  # dentro de una consulta: descartado
        ev(4, 1, "agregar", "5 de cerveza ZQXPRIV2", producto="cerveza ZQXPRIV2", cantidad="5"),
    ]
    with caplog.at_level(logging.DEBUG):
        r = procesar(rec, mensajes, eventos, cliente="K01", consultas=[frag(1, "¿tienen frijol ZQXPRIV2?")],
                     rechazadas=[frag(0, "Persona Inventada")])
    texto_diag = repr(r.diagnostico)
    for marca in MARCAS + ["K01", "P-0010", "P-0009", "Tienda Ficticia"]:
        assert marca not in texto_diag, marca
        assert marca not in r.mensaje_cliente, marca
    pendientes = r.cierre.pendientes
    assert any("ZQXPRIV2" in p.texto for p in pendientes)  # control: los textos sí van en la respuesta
    assert r.diagnostico.omisiones  # la gaseosa omitida es un pendiente por omisión
    nombres_catalogo = {p.nombre for p in rec.datos.productos.values()}
    for p in pendientes:
        assert p.texto not in texto_diag
        if p.texto not in nombres_catalogo:  # el nombre del catálogo de un agotado sí puede ir (D14)
            assert p.texto not in r.mensaje_cliente
    assert r.diagnostico.habitual_usado is True
    assert caplog.records == []


def test_error_de_limites_sin_contenido(rec):
    with pytest.raises(LimitesExcedidos) as error:
        procesar(rec, ["hola"], consultas=[frag(0, "ZQXPRIV2 consulta")] * 11, rechazadas=[frag(0, "ZQXPRIV2 rechazo")] * 10)
    assert "ZQXPRIV2" not in str(error.value) and "ZQXPRIV2" not in repr(error.value.args)


@pytest.mark.parametrize(
    "ruta", ["app/dominio/omisiones.py", "app/dominio/pedido.py", "app/dominio/clasificacion.py", "app/mensajes/confirmacion.py"]
)
def test_modulos_de_e1b2b_sin_logging_ni_print(ruta):
    arbol = ast.parse((RAIZ / ruta).read_text(encoding="utf-8"))
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados |= {a.name.split(".")[0] for a in nodo.names}
        elif isinstance(nodo, ast.ImportFrom):
            importados.add((nodo.module or "").split(".")[0])
    assert not importados & {"logging", "mlflow", "warnings"}
    llamadas = {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "print" not in llamadas
