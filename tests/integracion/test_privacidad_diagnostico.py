"""Privacidad: el diagnóstico no contiene texto de los mensajes, texto de pendientes, nombres,
`cliente_id` ni `pedido_id`; el dominio no escribe logs; las excepciones no llevan identificadores."""

import ast
import logging
from pathlib import Path

import pytest

from app.dominio.habitual import HistorialInconsistente
from tests.fixtures.historial_e1b2 import cargar_contexto, ev, plegar_mensajes

RAIZ = Path(__file__).resolve().parents[2]
MARCAS = ["ZQXPRIV1", "Persona Ficticia", "WKMARCA", "7777-1234"]


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("priv"))


def test_diagnostico_sin_textos_ni_identificadores(ctx, caplog):
    mensajes = [
        "Hola, soy Persona Ficticia, mi número es 7777-1234. ZQXPRIV1 2 de aceite WKMARCA",
        "y 3 de cerveza ZQXPRIV1, lo de siempre",
        "mejor 5 de la gaseosa sol 600 ml de 5 litros ZQXPRIV1",
    ]
    eventos = [
        ev(1, 0, "agregar", "ZQXPRIV1 2 de aceite WKMARCA", producto="aceite WKMARCA", cantidad="2"),
        ev(2, 1, "agregar", "3 de cerveza ZQXPRIV1", producto="cerveza ZQXPRIV1", cantidad="3"),
        ev(3, 1, "habitual", "lo de siempre"),
        ev(4, 2, "agregar", "mejor 5 de la gaseosa sol 600 ml de 5 litros ZQXPRIV1", producto="gaseosa sol 600 ml de 5 litros", cantidad="5"),
    ]
    with caplog.at_level(logging.DEBUG):
        rp, sal, _ = plegar_mensajes(ctx, mensajes, eventos, cliente="K01")
    d = rp.diagnostico(sal)
    texto = repr(d)
    for marca in MARCAS + ["K01", "P-0010", "P-0009", "Tienda Ficticia"]:
        assert marca not in texto, marca
    for pendiente in rp.pendientes():  # el texto de los pendientes va solo en la respuesta
        if len(pendiente.texto) >= 4:
            assert pendiente.texto not in texto, pendiente.texto
    assert any("ZQXPRIV1" in p.texto for p in rp.pendientes())  # control: el texto sí está en los pendientes
    assert d.habitual_usado is True
    assert caplog.records == []  # el dominio no escribe logs


def test_excepcion_de_duplicados_sin_identificadores():
    error = HistorialInconsistente("WKMARCA-CLIENTE", "WKMARCA-PEDIDO")
    for texto in (str(error), repr(error), repr(error.args)):
        assert "WKMARCA" not in texto


@pytest.mark.parametrize(
    "modulo", ["habitual", "atributos", "plegado", "sustitucion", "diagnostico", "limites"]
)
def test_modulos_de_e1b2a_sin_logging_ni_mlflow(modulo):
    arbol = ast.parse((RAIZ / "app" / "dominio" / f"{modulo}.py").read_text(encoding="utf-8"))
    importados = {
        (n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in ast.walk(arbol) if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [None])
    }
    assert not importados & {"logging", "mlflow", "print"}
    llamadas = {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "print" not in llamadas
