"""E2b: arranque (D24, D68), configuración y ejecución sin access log (D88)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import DIR_DATOS_POR_DEFECTO, Configuracion
from app.main import ErrorArranque, crear_app
from tests.fixtures import historial_e1b2
from tests.fixtures.api_e2b import RUTA, solicitud
from tests.fixtures.interprete_falso import InterpreteFijo


def test_configuracion_desde_el_entorno():
    assert Configuracion.desde_entorno({}).dir_datos == Path(DIR_DATOS_POR_DEFECTO)
    assert Configuracion.desde_entorno({"DATA_DIR": "/datos/ro"}).dir_datos == Path("/datos/ro")
    assert Configuracion.desde_entorno({"DATA_DIR": ""}).dir_datos == Path(DIR_DATOS_POR_DEFECTO)


def test_arranca_con_datos_validos_de_data_dir(tmp_path, monkeypatch):
    directorio = historial_e1b2.escribir(tmp_path / "datos")
    monkeypatch.setenv("DATA_DIR", str(directorio))
    with TestClient(crear_app()) as cliente:
        assert cliente.get("/health").status_code == 200
        assert cliente.post(RUTA, json=solicitud()).status_code == 503  # intérprete no configurado (D80)


def test_no_arranca_si_faltan_los_datos(tmp_path):
    with pytest.raises(ErrorArranque) as error:
        with TestClient(crear_app(configuracion=Configuracion(tmp_path / "no-existe"))):
            pass
    assert "ARCHIVO_FALTANTE (productos.parquet)" in str(error.value)


def test_no_arranca_con_datos_invalidos_y_el_error_no_muestra_claves(tmp_path):
    directorio = historial_e1b2.escribir(tmp_path / "datos")
    (directorio / "clientes.parquet").write_bytes(b"esto no es parquet")
    with pytest.raises(ErrorArranque) as error:
        with TestClient(crear_app(configuracion=Configuracion(directorio))):
            pass
    assert "ARCHIVO_ILEGIBLE (clientes.parquet)" in str(error.value)
    assert error.value.__cause__ is None and error.value.__suppress_context__  # sin la cadena con claves


def test_el_error_de_arranque_solo_incluye_codigos_y_archivos(tmp_path):
    import pandas as pd

    directorio = historial_e1b2.escribir(tmp_path / "datos")
    clientes = pd.read_parquet(directorio / "clientes.parquet")
    clientes.loc[0, "cliente_id"] = "ZQXCLAVE01"
    clientes.loc[0, "limite_credito"] = -5  # inválido: el problema lleva el cliente_id como clave
    clientes.to_parquet(directorio / "clientes.parquet")
    with pytest.raises(ErrorArranque) as error:
        with TestClient(crear_app(configuracion=Configuracion(directorio))):
            pass
    assert "ZQXCLAVE01" not in str(error.value) and "(clientes.parquet)" in str(error.value)


def test_importar_el_modulo_no_carga_datos(monkeypatch):
    # `app.main:app` existe sin datos: se cargan al arrancar (lifespan), no al importar.
    assert main.app is not None and not hasattr(main.app.state, "servicio")


def test_los_recursos_se_construyen_una_vez(ctx, monkeypatch):
    import app.main as modulo

    llamadas = []
    original = modulo.Recursos.construir

    def espia(datos, *args, **kwargs):
        llamadas.append(datos)
        return original(datos, *args, **kwargs)

    monkeypatch.setattr(modulo.Recursos, "construir", staticmethod(espia))
    with TestClient(crear_app(datos=ctx.datos, interprete=InterpreteFijo({"eventos": []}))) as cliente:
        for _ in range(3):
            cliente.post(RUTA, json=solicitud())
    assert len(llamadas) == 1


def test_ejecutar_usa_el_puerto_8000_sin_access_log(monkeypatch):
    import uvicorn

    capturado = {}
    monkeypatch.setattr(uvicorn, "run", lambda aplicacion, **opciones: capturado.update(opciones, app=aplicacion))
    monkeypatch.setattr(main.logging, "basicConfig", lambda **_: None)  # no alterar el logging de la sesión
    main.ejecutar()
    assert capturado["port"] == 8000 and capturado["access_log"] is False and capturado["app"] is main.app
