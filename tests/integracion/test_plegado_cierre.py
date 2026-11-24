"""Plegado + sustituciones -> cierre de E1a (sin modificarlo): la salida cumple su contrato."""

from decimal import Decimal

import pytest

from app.dominio.cierre import cerrar_pedido
from app.dominio.estado import verificar_invariantes
from app.dominio.resultado import Estado, Motivo
from tests.fixtures.historial_e1b2 import MARTES, cargar_contexto, ev, plegar_mensajes

D = Decimal


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("cierre"))


def cerrar(ctx, mensajes, eventos, cliente):
    rp, sal, entrada = plegar_mensajes(ctx, mensajes, eventos, cliente=cliente)
    r = cerrar_pedido(
        cliente_id=cliente, fecha_hora=MARTES, lineas_solicitadas=sal.lineas, pendientes=rp.pendientes(),
        sustituciones=sal.sustituciones, hay_eventos_pedido=True, datos=ctx.datos,
    )
    verificar_invariantes(r)
    return r


def test_habitual_con_sustituciones_y_pendientes(ctx):
    r = cerrar(ctx, ["lo de siempre"], [ev(1, 0, "habitual", "lo de siempre")], "K01")
    assert r.estado is Estado.REQUIERE_REVISION
    assert [(l.sku, l.cantidad) for l in r.lineas] == [("GS2", D(3)), ("AC1", D(1)), ("PC2", D(2))]
    assert [(s.sku_solicitado, s.sku_entregado) for s in r.sustituciones] == [("GS3", "GS2"), ("AC2", "AC1")]
    assert r.motivos_revision == (Motivo.AGOTADO_SIN_SUSTITUTO, Motivo.PRODUCTO_NO_EXISTE)


def test_confirmado(ctx):
    r = cerrar(ctx, ["2 fardos de gaseosa sol 600 y 3 de frijol negro"], [
        ev(1, 0, "agregar", "2 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2"),
        ev(2, 0, "agregar", "3 de frijol negro", producto="frijol negro", cantidad="3"),
    ], "K04")
    assert r.estado is Estado.CONFIRMADO and r.total == D("725.00")  # 2x100 + 3x175


def test_d48c_llega_al_cierre_con_la_linea_original_y_el_pendiente(ctx):
    r = cerrar(ctx, ["12 botellas de gaseosa sol de 2 litros", "mejor la de 600"], [
        ev(1, 0, "agregar", "12 botellas de gaseosa sol de 2 litros", producto="gaseosa sol", presentacion="2 litros", cantidad="12", unidad="suelta", unidad_texto="botellas"),
        ev(2, 1, "corregir", "mejor la de 600", presentacion="600 ml", ref="e1"),
    ], "K04")
    assert [(l.sku, l.cantidad) for l in r.lineas] == [("GS2", D(2))]
    assert r.motivos_revision == (Motivo.CANTIDAD_NO_CONVERTIBLE,)


def test_sustituto_y_linea_directa_respetan_la_validacion_del_cierre(ctx):
    r = cerrar(ctx, ["1 de gaseosa sol 3 L y 2 de gaseosa sol de 2 litros"], [
        ev(1, 0, "agregar", "1 de gaseosa sol 3 L", producto="gaseosa sol", presentacion="3 L", cantidad="1"),
        ev(2, 0, "agregar", "2 de gaseosa sol de 2 litros", producto="gaseosa sol", presentacion="2 litros", cantidad="2"),
    ], "K04")
    assert [(l.sku, l.cantidad) for l in r.lineas] == [("GS2", D(3))] and r.sustituciones[0].cantidad == D(1)


def test_credito_con_lineas_del_plegado(ctx):
    r = cerrar(ctx, ["1 de cloro claro"], [ev(1, 0, "agregar", "1 de cloro claro", producto="cloro claro", cantidad="1")], "K02")
    assert r.estado is Estado.REQUIERE_REVISION and r.motivos_revision == (Motivo.CREDITO_EXCEDIDO,)
