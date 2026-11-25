"""E2b con los datos reales (local): los 84 casos de desarrollo y Q-N1 **por HTTP**.

El intérprete de referencia existe **solo en esta prueba** (D80): reconstruye la interpretación
de cada caso desde `eventos_dev.json` y los mensajes de `EVAL_DEV_PATH`. La respuesta debe tener
las claves del Anexo y los campos y valores esperados, con los montos numéricamente iguales
(D91, opción A: la igualdad textual no es un criterio). La latencia se informa (sin umbral).
"""

import json
import statistics
import time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.datos.normalizacion import normalizar_texto
from app.main import crear_app
from tests.referencia.formato_eventos_dev import cargar, reconstruir
from tests.referencia.test_consultas_qn1 import CONSULTAS, PEDIDOS

RUTA = "/v1/pedidos/interpretar"
CLAVES = {"cliente_id", "estado", "lineas", "total", "fecha_entrega", "sustituciones", "pendientes", "motivos_revision", "mensaje_cliente"}


class InterpreteReferencia:
    """Solo para pruebas: interpretación de referencia por (cliente, mensajes)."""

    def __init__(self, casos):
        documento = cargar()
        self.por_entrada = {
            (c["entrada"]["cliente_id"], tuple(c["entrada"]["mensajes"])): reconstruir(documento["casos"][c["id"]], c["entrada"]["mensajes"])
            for c in casos
        }

    def interpretar(self, entrada):
        return self.por_entrada[(entrada.cliente_id, entrada.mensajes)]

    def estado(self):
        return True, None


def _normalizado(cuerpo):
    return {
        "estado": cuerpo["estado"],
        "lineas": [(l["sku"], Decimal(l["cantidad"]), l["precio_unitario"], Decimal(l["descuento_pct"]), l["subtotal"]) for l in cuerpo["lineas"]],
        "total": cuerpo["total"],
        "fecha_entrega": cuerpo["fecha_entrega"],
        "sustituciones": [(s["sku_solicitado"], s["sku_entregado"], Decimal(s["cantidad"])) for s in cuerpo["sustituciones"]],
        "pendientes": [(p["motivo"], normalizar_texto(p["texto"]), list(p["opciones"])) for p in cuerpo["pendientes"]],
        "motivos_revision": list(cuerpo["motivos_revision"]),
    }


def test_los_84_casos_por_http(casos_dev, datos_reales):
    discrepancias, latencias = {}, []
    with TestClient(crear_app(datos=datos_reales, interprete=InterpreteReferencia(casos_dev))) as cliente:
        assert cliente.get("/health").json() == {"estado": "ok"}
        for caso in casos_dev:
            inicio = time.perf_counter()
            respuesta = cliente.post(RUTA, json=caso["entrada"])
            latencias.append((time.perf_counter() - inicio) * 1000)
            assert respuesta.status_code == 200, caso["id"]
            cuerpo = json.loads(respuesta.text, parse_float=Decimal)
            assert set(cuerpo) == CLAVES and cuerpo["cliente_id"] == caso["entrada"]["cliente_id"], caso["id"]
            assert all(set(l) == {"sku", "cantidad", "precio_unitario", "descuento_pct", "subtotal"} for l in cuerpo["lineas"])
            o, e = _normalizado(cuerpo), _normalizado(caso["esperado"])
            diferencias = sorted(k for k in e if o[k] != e[k])  # solo nombres de campo
            if diferencias:
                discrepancias[caso["id"]] = diferencias
    p50 = statistics.median(latencias)
    p95 = sorted(latencias)[int(len(latencias) * 0.95) - 1]
    print(f"\nRespuesta por HTTP: {len(casos_dev) - len(discrepancias)}/{len(casos_dev)}; latencia sin LLM p50 {p50:.1f} ms, p95 {p95:.1f} ms (informativa)")
    assert len(casos_dev) == 84 and discrepancias == {}


class InterpreteQN1:
    """Solo para pruebas: un evento `agregar` sobre el fragmento del producto."""

    def __init__(self, casos):
        self.por_mensajes = {}
        for caso in casos:
            indice = next(i for i, m in enumerate(caso["mensajes"]) if caso["fragmento"] in m)
            self.por_mensajes[tuple(caso["mensajes"])] = {"eventos": [
                {"id": "e1", "mensaje": indice, "tipo": "agregar", "texto": caso["fragmento"], "producto": caso["fragmento"]}
            ]}

    def interpretar(self, entrada):
        return self.por_mensajes[entrada.mensajes]

    def estado(self):
        return True, None


@pytest.fixture(scope="module")
def cliente_qn1(datos_reales):
    with TestClient(crear_app(datos=datos_reales, interprete=InterpreteQN1(CONSULTAS + PEDIDOS))) as cliente:
        yield cliente, sorted(datos_reales.clientes)[0]


@pytest.mark.parametrize("caso", CONSULTAS, ids=[c["id"] for c in CONSULTAS])
def test_consultas_qn1_por_http(cliente_qn1, caso):
    cliente, cliente_id = cliente_qn1
    cuerpo = cliente.post(RUTA, json={"cliente_id": cliente_id, "fecha_hora": "2026-11-24T10:00", "mensajes": caso["mensajes"]}).json()
    assert (cuerpo["estado"], cuerpo["lineas"], cuerpo["pendientes"]) == ("fuera_de_alcance", [], [])


@pytest.mark.parametrize("caso", PEDIDOS, ids=[c["id"] for c in PEDIDOS])
def test_pedidos_interrogativos_por_http(cliente_qn1, caso):
    cliente, cliente_id = cliente_qn1
    cuerpo = cliente.post(RUTA, json={"cliente_id": cliente_id, "fecha_hora": "2026-11-24T10:00", "mensajes": caso["mensajes"]}).json()
    assert cuerpo["estado"] != "fuera_de_alcance"
