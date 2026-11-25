"""E2b: privacidad de la API. Ni las respuestas de error ni los logs contienen el cuerpo, los
mensajes, el `cliente_id`, el texto de los pendientes ni detalles internos."""

import logging

import pytest

import app.servicio as servicio
from tests.fixtures.api_e2b import RUTA, solicitud
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.interprete_falso import InterpreteFijo, InterpreteQueFalla

MARCA = "ZQXPRIVAPI"


def textos_de_log(caplog):
    return " ".join(r.getMessage() for r in caplog.records) + " ".join(str(r.args) for r in caplog.records)


def test_200_no_registra_mensajes_ni_cliente(cliente_con, caplog):
    mensajes = [f"Soy {MARCA}, mándeme 2 de frijol negro y 3 de cerveza {MARCA}"]
    interpretacion = {"eventos": [
        ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2"),
        ev(2, 0, "agregar", f"3 de cerveza {MARCA}", producto=f"cerveza {MARCA}", cantidad="3"),
    ]}
    with caplog.at_level(logging.DEBUG), cliente_con(InterpreteFijo(interpretacion)) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud(mensajes, cliente="K04"))
    assert respuesta.status_code == 200
    assert any(MARCA in p["texto"] for p in respuesta.json()["pendientes"])  # el texto sí va en la respuesta
    log = textos_de_log(caplog)
    assert MARCA not in log and "K04" not in log
    assert any("-> 200" in r.getMessage() for r in caplog.records)  # el log propio existe, pero es mínimo


def test_404_no_registra_ni_devuelve_el_cliente(cliente_con, caplog):
    with caplog.at_level(logging.DEBUG), cliente_con(InterpreteFijo({"eventos": []})) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud(cliente=f"{MARCA}-CLIENTE"))
    assert respuesta.status_code == 404 and MARCA not in respuesta.text and MARCA not in textos_de_log(caplog)


def test_422_no_registra_el_valor(cliente_con, caplog):
    with caplog.at_level(logging.DEBUG), cliente_con() as cliente:
        respuesta = cliente.post(RUTA, json={"cliente_id": MARCA * 30, "fecha_hora": MARCA, "mensajes": [MARCA]})
    assert respuesta.status_code == 422 and MARCA not in respuesta.text and MARCA not in textos_de_log(caplog)


def test_503_y_500_no_registran_detalles(cliente_con, caplog, monkeypatch):
    with caplog.at_level(logging.DEBUG):
        with cliente_con(InterpreteQueFalla(RuntimeError(MARCA))) as cliente:
            assert cliente.post(RUTA, json=solicitud([MARCA])).status_code == 503

        def falla(*args, **kwargs):
            raise RuntimeError(f"interno {MARCA}")

        monkeypatch.setattr(servicio, "procesar_pedido", falla)
        with cliente_con(InterpreteFijo({"eventos": []})) as cliente:
            respuesta = cliente.post(RUTA, json=solicitud([MARCA]))
    assert respuesta.status_code == 500 and MARCA not in respuesta.text
    log = textos_de_log(caplog)
    assert MARCA not in log and "(RuntimeError)" in log  # solo el tipo del error, nunca su mensaje


def test_ningun_log_de_errores_lleva_traceback_con_contenido(cliente_con, caplog, monkeypatch):
    def falla(*args, **kwargs):
        raise ValueError(MARCA)

    monkeypatch.setattr(servicio, "procesar_pedido", falla)
    with caplog.at_level(logging.DEBUG), cliente_con(InterpreteFijo({"eventos": []})) as cliente:
        cliente.post(RUTA, json=solicitud())
    assert all(r.exc_info is None for r in caplog.records)


@pytest.mark.parametrize("ruta", ["app/api/rutas.py", "app/api/salud.py", "app/api/limites_http.py", "app/servicio.py", "app/main.py", "app/interprete/base.py"])
def test_modulos_sin_print(ruta):
    import ast
    from pathlib import Path

    arbol = ast.parse((Path(__file__).resolve().parents[2] / ruta).read_text(encoding="utf-8"))
    assert "print" not in {n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
