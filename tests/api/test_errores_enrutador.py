"""E2b: errores del enrutador, fuera del contrato del Anexo (opción A aprobada en la revisión del PR #7).

- Ruta inexistente: 404 `{"detail": "Ruta no encontrada"}`.
- Método no permitido: 405 `{"detail": "Método no permitido"}` con el encabezado `Allow`.
- Ninguna de las dos revela la ruta, los parámetros ni los valores recibidos.
- El 404 de negocio (cliente inexistente, D79) conserva `{"detail": "Cliente no encontrado"}`.
"""

import logging

import pytest

from tests.fixtures.api_e2b import RUTA, solicitud
from tests.fixtures.interprete_falso import InterpreteFijo, InterpreteQueFalla

MARCA = "ZQXRUTA"
RUTA_NO_ENCONTRADA = {"detail": "Ruta no encontrada"}
METODO_NO_PERMITIDO = {"detail": "Método no permitido"}


@pytest.mark.parametrize(
    "url",
    [f"/{MARCA}", f"/v1/{MARCA}/interpretar", f"/v1/pedidos/interpretar/{MARCA}", f"/no-existe?{MARCA}=1&q={MARCA}",
     f"/v2/pedidos/interpretar", "/", "/v1/pedidos", f"/health/{MARCA}"],
)
@pytest.mark.parametrize("metodo", ["get", "post", "put", "delete"])
def test_ruta_inexistente_404_fijo_y_sin_eco(cliente_con, url, metodo, caplog):
    with caplog.at_level(logging.DEBUG), cliente_con() as cliente:
        respuesta = getattr(cliente, metodo)(url)
    assert respuesta.status_code == 404 and respuesta.json() == RUTA_NO_ENCONTRADA
    assert MARCA not in respuesta.text and "/" not in respuesta.json()["detail"]
    # El log del servidor tampoco guarda la ruta (httpx es el cliente de prueba, no el servidor).
    assert all(MARCA not in r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))


@pytest.mark.parametrize(
    ("metodo", "url", "permitido"),
    [("get", RUTA, "POST"), ("put", RUTA, "POST"), ("delete", RUTA, "POST"), ("patch", RUTA, "POST"),
     ("post", "/health", "GET"), ("put", "/health", "GET"), ("delete", "/health", "GET")],
)
def test_metodo_no_permitido_405_fijo_con_allow(cliente_con, metodo, url, permitido):
    with cliente_con() as cliente:
        respuesta = getattr(cliente, metodo)(url)
    assert respuesta.status_code == 405 and respuesta.json() == METODO_NO_PERMITIDO
    assert respuesta.headers["allow"] == permitido


def test_405_no_revela_el_cuerpo_ni_los_parametros(cliente_con):
    with cliente_con() as cliente:
        respuesta = cliente.request("PUT", f"{RUTA}?{MARCA}=1", json={"cliente_id": MARCA, "mensajes": [MARCA]})
    assert respuesta.status_code == 405 and respuesta.json() == METODO_NO_PERMITIDO and MARCA not in respuesta.text


@pytest.mark.parametrize("interprete", [None, InterpreteQueFalla(), InterpreteFijo({"eventos": []})], ids=["no_configurado", "que_falla", "fijo"])
def test_el_404_de_negocio_no_cambia(cliente_con, interprete):
    with cliente_con(interprete) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud(cliente=f"{MARCA}-CLIENTE"))
    assert respuesta.status_code == 404 and respuesta.json() == {"detail": "Cliente no encontrado"}
    assert MARCA not in respuesta.text


def test_los_dos_404_se_distinguen(cliente_con):
    with cliente_con() as cliente:
        de_ruta = cliente.post("/v1/pedidos/otra", json=solicitud())
        de_negocio = cliente.post(RUTA, json=solicitud(cliente="NO-EXISTE"))
    assert de_ruta.json() == RUTA_NO_ENCONTRADA and de_negocio.json() == {"detail": "Cliente no encontrado"}


def test_las_rutas_del_contrato_siguen_respondiendo(cliente_con):
    with cliente_con(InterpreteFijo({"eventos": []})) as cliente:
        assert cliente.get("/health").status_code == 200
        assert cliente.post(RUTA, json=solicitud()).status_code == 200
        assert cliente.post(RUTA, json={"cliente_id": ""}).status_code == 422  # el 422 no cambia
