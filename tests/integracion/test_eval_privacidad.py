"""E2c-1: ningún contenido de los casos llega a los reportes, a la salida en pantalla, a los logs ni
a los errores. Solo datos sintéticos con la marca «zqxsecreto» en los mensajes, los textos de los
pendientes, las respuestas esperadas y las claves."""

import copy
import json
import logging
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.datos.carga import cargar_datos
from app.main import crear_app
from evaluacion.__main__ import ejecutar
from evaluacion.cliente import ClienteEvaluacion
from evaluacion.criticos import ResultadoCaso
from tests.fixtures.evaluacion_e2c import anotacion_json, escribir_conjunto
from tests.fixtures.historial_e1b2 import escribir as escribir_datos
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.interprete_falso import InterpretePorFuncion

RAIZ = Path(__file__).resolve().parents[2]
MARCA = "zqxsecreto"
MENSAJES = {
    "2 fardos de frijol negro zqxsecretoalfa": ([ev(1, 0, "agregar", "2 fardos de frijol negro", producto="frijol negro", cantidad="2", unidad="venta", unidad_texto="fardos")],
                                                [[["frijol", "negro"]]]),
    "zqxpido zqxsecretobeta": ([ev(1, 0, "agregar", "zqxsecretobeta", producto="zqxsecretobeta")], [[["zqxsecretobeta"]]]),
}
CAMPOS_PERMITIDOS = {f for f in ResultadoCaso.__dataclass_fields__} | {"correcto"}


def interpretar(entrada):
    return {"eventos": MENSAJES[entrada.mensajes[0]][0]}


@pytest.fixture(scope="module")
def entorno_app(tmp_path_factory):
    directorio = escribir_datos(tmp_path_factory.mktemp("datos_priv"))
    return directorio, crear_app(datos=cargar_datos(directorio), interprete=InterpretePorFuncion(interpretar))


def _preparar(tmp_path, app, alterar_esperado=False):
    with TestClient(app) as tc:
        esperados = {}
        for m in MENSAJES:
            r = tc.post("/v1/pedidos/interpretar", json={"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00", "mensajes": [m]})
            cuerpo = json.loads(r.text, parse_float=Decimal, parse_int=Decimal)
            esperados[m] = {k: v for k, v in cuerpo.items() if k not in ("cliente_id", "mensaje_cliente")}
    assert any(MARCA in p["texto"] for e in esperados.values() for p in e["pendientes"])  # la marca está en las esperadas
    entradas, entorno = [], {}
    for rol in ("validacion_publica", "validacion_privada"):
        casos, anot = [], {}
        for i, (m, (_, claves)) in enumerate(MENSAJES.items()):
            esp = copy.deepcopy(esperados[m])
            if alterar_esperado:
                esp["pendientes"] = [dict(p, texto=p["texto"] + " " + MARCA) for p in esp["pendientes"]]
                esp["estado"] = "confirmado"
            casos.append({"id": f"{rol[:3].upper()}{i}", "tipo": "sintetico", "entrada": {"cliente_id": "K04", "fecha_hora": "2026-12-01T10:00", "mensajes": [m]}, "esperado": esp})
            anot[f"{rol[:3].upper()}{i}"] = anotacion_json(claves)
        d, rutas = escribir_conjunto(tmp_path / rol, casos, anot, rol=rol, id=f"sint_{rol}", privado=rol == "validacion_privada")
        archivos = {}
        for nombre, ruta in rutas.items():
            entorno[f"V_{rol}_{nombre}"] = str(ruta)
            archivos[nombre] = {"sha256": d.sha256[nombre], "variable": f"V_{rol}_{nombre}"}
        entradas.append({"id": d.id, "rol": rol, "n_casos": d.n_casos, "privado": d.privado, "archivos": archivos})
    registro = tmp_path / "registro.json"
    registro.write_text(json.dumps(entradas), encoding="utf-8")
    return registro, entorno


@pytest.mark.parametrize("alterar_esperado", [False, True], ids=["aciertos", "fallos"])
def test_marcas_ausentes_de_reportes_pantalla_y_logs(tmp_path, entorno_app, caplog, capsys, alterar_esperado):
    directorio, app = entorno_app
    registro, entorno = _preparar(tmp_path, app, alterar_esperado)
    caplog.set_level(logging.DEBUG)
    lineas = []
    with TestClient(app, raise_server_exceptions=False) as tc:
        codigo = ejecutar("e6", registro, "http://testserver", 5, tmp_path / "salida", {**entorno, "DATA_DIR": str(directorio)},
                          cliente=ClienteEvaluacion(cliente=tc), raiz=RAIZ, verificar_arbol=False, salida_texto=lineas.append)
    assert codigo == (1 if alterar_esperado else 0)
    (carpeta,) = list((tmp_path / "salida").iterdir())
    textos = [p.read_text(encoding="utf-8") for p in carpeta.iterdir()] + lineas + [caplog.text, capsys.readouterr().out]
    assert all(MARCA not in t.lower() for t in textos)
    privado = json.loads((carpeta / "reporte_privado.json").read_text())
    for conjunto in privado["conjuntos"].values():
        for repeticion in conjunto["casos"]:
            assert all(set(c) <= CAMPOS_PERMITIDOS for c in repeticion)


def test_fallo_de_integridad_no_muestra_contenido(tmp_path, entorno_app, capsys):
    directorio, app = entorno_app
    registro, entorno = _preparar(tmp_path, app)
    ruta = Path(entorno["V_validacion_privada_casos"])
    ruta.write_text(ruta.read_text(encoding="utf-8").replace("zqxsecretobeta", "zqxsecretogamma"), encoding="utf-8")
    lineas = []
    codigo = ejecutar("e6", registro, "http://x", 5, tmp_path / "salida", {**entorno, "DATA_DIR": str(directorio)}, raiz=RAIZ, verificar_arbol=False,
                      salida_texto=lineas.append)
    assert codigo == 2 and lineas == ["HASH_DISTINTO"] and MARCA not in capsys.readouterr().out
