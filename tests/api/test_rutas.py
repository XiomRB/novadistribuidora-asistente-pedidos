"""E2b: `POST /v1/pedidos/interpretar` con intérpretes de prueba sobre el catálogo sintético.

La respuesta HTTP es exactamente la salida del motor (E1b) traducida por el esquema (E2a): las
claves del Anexo en cada nivel (como conjunto, sin importar el orden) y los montos
numéricamente iguales.
"""

import json
from decimal import Decimal

import pytest

from app.dominio import cierre
from app.dominio.entrada import EntradaPedido
from app.dominio.esquema_eventos import Interpretacion
from app.dominio.pedido import Recursos, procesar_pedido
from tests.fixtures.api_e2b import MARTES, RUTA, solicitud
from tests.fixtures.historial_e1b2 import MARTES as MARTES_DT
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.interprete_falso import InterpreteFijo

CLAVES = {"cliente_id", "estado", "lineas", "total", "fecha_entrega", "sustituciones", "pendientes", "motivos_revision", "mensaje_cliente"}

PEDIDO = ["2 fardos de gaseosa sol 600 y 3 de frijol negro"]
EVENTOS_PEDIDO = {"eventos": [
    ev(1, 0, "agregar", "2 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2"),
    ev(2, 0, "agregar", "3 de frijol negro", producto="frijol negro", cantidad="3"),
]}


def directo(ctx, mensajes, interpretacion, cliente="K04"):
    entrada = EntradaPedido(cliente, MARTES_DT, tuple(mensajes))
    return procesar_pedido(entrada, interpretacion, ctx.datos, recursos=Recursos.construir(ctx.datos))


def test_200_con_el_contrato_y_los_valores_del_motor(ctx, cliente_con):
    interprete = InterpreteFijo(EVENTOS_PEDIDO)
    with cliente_con(interprete) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud(PEDIDO))
    assert respuesta.status_code == 200 and respuesta.headers["content-type"].startswith("application/json")
    cuerpo = respuesta.json()
    assert set(cuerpo) == CLAVES
    assert all(set(l) == {"sku", "cantidad", "precio_unitario", "descuento_pct", "subtotal"} for l in cuerpo["lineas"])
    numerico = json.loads(respuesta.text, parse_float=Decimal)
    esperado = directo(ctx, PEDIDO, EVENTOS_PEDIDO).cierre
    assert numerico["total"] == esperado.total == Decimal("725.00")
    assert [(l["sku"], l["cantidad"], l["subtotal"]) for l in numerico["lineas"]] == [(l.sku, l.cantidad, l.subtotal) for l in esperado.lineas]
    assert cuerpo["estado"] == "confirmado" and cuerpo["cliente_id"] == "K04" and cuerpo["fecha_entrega"] == "2026-12-02"
    assert isinstance(cuerpo["total"], float) and cuerpo["mensaje_cliente"].startswith("¡Buenos días!")


def test_el_interprete_recibe_la_entrada_validada(cliente_con):
    interprete = InterpreteFijo(EVENTOS_PEDIDO)
    with cliente_con(interprete) as cliente:
        cliente.post(RUTA, json=solicitud(PEDIDO, extra="ignorado"))
    (entrada,) = interprete.llamadas
    assert (entrada.cliente_id, entrada.fecha_hora.isoformat(timespec="minutes"), entrada.mensajes) == ("K04", MARTES, tuple(PEDIDO))


@pytest.mark.parametrize("forma", ["dict", "json", "modelo"])
def test_el_interprete_puede_devolver_dict_json_o_modelo(cliente_con, forma):
    interpretacion = {"dict": EVENTOS_PEDIDO, "json": json.dumps(EVENTOS_PEDIDO), "modelo": Interpretacion.validar(EVENTOS_PEDIDO, 1)}[forma]
    with cliente_con(InterpreteFijo(interpretacion)) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud(PEDIDO))
    assert respuesta.status_code == 200 and respuesta.json()["total"] == 725.0


def test_habitual_con_sustituciones_y_pendientes(ctx, cliente_con):
    interpretacion = {"eventos": [ev(1, 0, "habitual", "lo de siempre")]}
    with cliente_con(InterpreteFijo(interpretacion)) as cliente:
        cuerpo = cliente.post(RUTA, json=solicitud(["lo de siempre"], cliente="K01")).json()
    esperado = directo(ctx, ["lo de siempre"], interpretacion, cliente="K01")
    assert cuerpo["estado"] == "requiere_revision"
    assert [(s["sku_solicitado"], s["sku_entregado"], s["cantidad"]) for s in cuerpo["sustituciones"]] == [("GS3", "GS2", 3), ("AC2", "AC1", 1)]
    assert [(p["motivo"], p["texto"], p["opciones"]) for p in cuerpo["pendientes"]] == [
        (p.motivo.value, p.texto, list(p.opciones)) for p in esperado.cierre.pendientes
    ]
    assert cuerpo["motivos_revision"] == ["agotado_sin_sustituto", "producto_no_existe"]
    assert cuerpo["mensaje_cliente"] == esperado.mensaje_cliente


# ====================================================================== tabla 3.9 por HTTP


ESCENARIOS = [
    ("consulta_pura", ["¿Tienen gaseosa sol de 600?"], {"eventos": []}, "fuera_de_alcance"),
    ("consulta_con_evento_erroneo", ["¿Cuánto cuesta el aceite girasol?"],
     {"eventos": [ev(1, 0, "agregar", "aceite girasol", producto="aceite girasol")]}, "fuera_de_alcance"),
    ("consulta_seguida_de_pedido", ["¿Tienen gaseosa sol de 600? Si hay, mándeme 2"],
     {"eventos": [ev(1, 0, "agregar", "mándeme 2", producto="gaseosa sol de 600", cantidad="2")]}, "confirmado"),
    ("pedido_en_pregunta", ["¿me manda 2 fardos de gaseosa sol 600?"],
     {"eventos": [ev(1, 0, "agregar", "2 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2")]}, "confirmado"),
    ("pedido_cancelado", ["2 de gaseosa sol 600", "no, mejor no me mande nada"],
     {"eventos": [ev(1, 0, "agregar", "2 de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2"),
                  ev(2, 1, "quitar", "no me mande nada", ref="e1")]}, "fuera_de_alcance"),
    ("quitar_sin_destino", ["quíteme la gaseosa del pedido de ayer"],
     {"eventos": [ev(1, 0, "quitar", "quíteme la gaseosa", producto="gaseosa")]}, "fuera_de_alcance"),
    ("omision", ["mándeme 3 fardos de gaseosa sol 600"], {"eventos": []}, "requiere_revision"),
]


@pytest.mark.parametrize(("nombre", "mensajes", "interpretacion", "estado"), ESCENARIOS, ids=[e[0] for e in ESCENARIOS])
def test_escenarios_por_http_coinciden_con_el_motor(ctx, cliente_con, nombre, mensajes, interpretacion, estado):
    with cliente_con(InterpreteFijo(interpretacion)) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud(mensajes))
    assert respuesta.status_code == 200
    cuerpo = json.loads(respuesta.text, parse_float=Decimal)
    esperado = directo(ctx, mensajes, interpretacion)
    assert cuerpo["estado"] == estado == esperado.cierre.estado.value
    assert cuerpo["total"] == esperado.cierre.total and cuerpo["mensaje_cliente"] == esperado.mensaje_cliente
    if estado == "fuera_de_alcance":
        assert (cuerpo["lineas"], cuerpo["fecha_entrega"], cuerpo["pendientes"], cuerpo["motivos_revision"]) == ([], None, [], [])


def test_prueba_a_cancelado_no_evalua_credito_por_http(cliente_con, monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("el crédito no debe evaluarse en un pedido cancelado")

    monkeypatch.setattr(cierre, "credito_excedido", prohibido)
    interpretacion = {"eventos": [ev(1, 0, "agregar", "2 de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2"),
                                  ev(2, 1, "quitar", "mejor no", ref="e1")]}
    with cliente_con(InterpreteFijo(interpretacion)) as cliente:
        respuesta = cliente.post(RUTA, json=solicitud(["2 de gaseosa sol 600", "mejor no"], cliente="K03"))
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "fuera_de_alcance" and respuesta.json()["total"] == 0.0


def test_credito_excedido_por_http(cliente_con):
    interpretacion = {"eventos": [ev(1, 0, "agregar", "1 de cloro claro", producto="cloro claro", cantidad="1")]}
    with cliente_con(InterpreteFijo(interpretacion)) as cliente:
        cuerpo = cliente.post(RUTA, json=solicitud(["1 de cloro claro"], cliente="K02")).json()
    assert cuerpo["estado"] == "requiere_revision" and cuerpo["motivos_revision"] == ["credito_excedido"]
