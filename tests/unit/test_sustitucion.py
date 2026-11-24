"""Sustituciones después del plegado."""

from decimal import Decimal

import pytest

from app.dominio.plegado import Clase, Item
from app.dominio.sustitucion import LineaNoEntregable, aplicar_sustituciones
from tests.fixtures.historial_e1b2 import cargar_contexto, ev, lineas, plegar_mensajes

D = Decimal


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("sus"))


def linea(id_, sku, cantidad):
    return Item(id=id_, clase=Clase.LINEA, sku=sku, cantidad=D(cantidad))


def test_habitual_con_agotados(ctx):
    rp, sal, _ = plegar_mensajes(ctx, ["lo de siempre"], [ev(1, 0, "habitual", "lo de siempre")], cliente="K01")
    assert lineas(sal) == [("GS2", "3"), ("AC1", "1"), ("PC2", "2")]
    assert [(s.sku_solicitado, s.sku_entregado, s.cantidad) for s in sal.sustituciones] == [("GS3", "GS2", D(3)), ("AC2", "AC1", D(1))]


def test_se_suma_a_una_linea_existente_en_su_primera_posicion(ctx):
    sal = aplicar_sustituciones([linea("i1", "AC1", 2), linea("i2", "GS6", 1), linea("i3", "AC2", 3)], ctx.datos)
    assert [(l.sku, l.cantidad) for l in sal.lineas] == [("AC1", D(5)), ("GS6", D(1))]
    assert [(s.sku_solicitado, s.sku_entregado, s.cantidad) for s in sal.sustituciones] == [("AC2", "AC1", D(3))]
    assert sal.items_por_linea == ("i1", "i2")


def test_sustituto_antes_que_la_linea_directa(ctx):
    sal = aplicar_sustituciones([linea("i1", "GS3", 2), linea("i2", "GS2", 4)], ctx.datos)
    assert [(l.sku, l.cantidad) for l in sal.lineas] == [("GS2", D(6))] and sal.items_por_linea == ("i1",)


def test_mismo_par_se_acumula(ctx):
    sal = aplicar_sustituciones([linea("i1", "GS3", 2), linea("i2", "GS3", 1)], ctx.datos)
    assert [(s.sku_solicitado, s.sku_entregado, s.cantidad) for s in sal.sustituciones] == [("GS3", "GS2", D(3))]


def test_agotado_sin_sustituto_no_puede_llegar_como_linea(ctx):
    with pytest.raises(LineaNoEntregable):
        aplicar_sustituciones([linea("i1", "GC1", 1)], ctx.datos)


def test_diagnostico_de_sustitucion(ctx):
    sal = aplicar_sustituciones([linea("i7", "PHD", 2)], ctx.datos)
    assert [(d.item, d.sku_solicitado, d.sku_entregado, d.cantidad) for d in sal.diagnostico] == [("i7", "PHD", "PH4", "2")]
