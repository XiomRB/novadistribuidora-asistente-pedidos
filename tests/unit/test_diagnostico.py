"""Diagnóstico: estructura, posiciones, D67 y D74."""

import pytest

from app.dominio.diagnostico import Diagnostico, posicion
from app.dominio.texto import Span
from tests.fixtures.historial_e1b2 import cargar_contexto, ev, plegar_mensajes


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    return cargar_contexto(tmp_path_factory.mktemp("diag"))


def test_posicion():
    assert posicion(Span(1, 4, 9)) == (1, 4, 9) and posicion(None) is None


def test_estructura_completa_con_apartados_de_e1b2b():
    d = Diagnostico()
    for campo in ("omisiones", "clasificacion", "consultas", "instrucciones_rechazadas", "eventos_descartados", "habitual_usado"):
        assert hasattr(d, campo)
    assert not hasattr(d, "pedido_id") and not hasattr(d, "cliente_id")


def test_eventos_con_posiciones_codigos_e_items(ctx):
    mensajes = ["hola, 2 fardos de gaseosa sol 600"]
    rp, sal, _ = plegar_mensajes(ctx, mensajes, [ev(1, 0, "agregar", "2 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2")])
    d = rp.diagnostico(sal)
    (e,) = d.eventos
    assert (e.evento, e.codigo, e.posicion, e.sku, e.cantidad, e.item) == ("e1", "RESUELTO", (0, 6, 33), "GS6", "2", "i1")
    assert d.salida_lineas == ("i1",) and d.items[0].origen == ("e1",)


def test_d67_medidas_explicitas_del_rechazo(ctx):
    mensajes = ["2 de gaseosa sol 600 ml de 5 litros"]
    rp, sal, _ = plegar_mensajes(ctx, mensajes, [
        ev(1, 0, "agregar", "2 de gaseosa sol 600 ml de 5 litros", producto="gaseosa sol 600 ml de 5 litros", cantidad="2"),
    ])
    (m,) = rp.diagnostico(sal).medidas_rechazo
    assert (m.evento, m.posicion, m.medidas, m.codigo) == ("e1", (0, 0, 35), ("5000ml", "600ml"), "MEDIDA_SIN_PRODUCTO")


def test_d67_numero_sin_unidad_no_se_registra_como_medida(ctx):
    rp, sal, _ = plegar_mensajes(ctx, ["gaseosa de 5 litros 3"], [
        ev(1, 0, "agregar", "gaseosa de 5 litros 3", producto="gaseosa de 5 litros 3"),
    ])
    assert rp.diagnostico(sal).medidas_rechazo[0].medidas == ("5000ml",)


def test_d74_indicador_sin_pedido_id(ctx):
    rp, sal, _ = plegar_mensajes(ctx, ["lo de siempre"], [ev(1, 0, "habitual", "lo de siempre")], cliente="K01")
    d = rp.diagnostico(sal)
    assert d.habitual_usado is True
    texto = repr(d)
    assert "P-0010" not in texto and "P-0009" not in texto and "K01" not in texto
    assert all("habitual" in item.origen for item in d.items)


def test_d74_falso_sin_habitual(ctx):
    rp, sal, _ = plegar_mensajes(ctx, ["2 de frijol negro"], [ev(1, 0, "agregar", "2 de frijol negro", producto="frijol negro", cantidad="2")])
    assert rp.diagnostico(sal).habitual_usado is False


def test_desacuerdos_llm(ctx):
    rp, sal, _ = plegar_mensajes(ctx, ["2 de gaseosa sol 600 ml"], [
        ev(1, 0, "agregar", "2 de gaseosa sol 600 ml", producto="gaseosa sol 600 ml", candidatos=["GS2", "ZZZ"], cantidad="2"),
    ])
    assert {(x.evento, x.codigo) for x in rp.diagnostico(sal).desacuerdos} == {("e1", "SKU_LLM_INEXISTENTE"), ("e1", "CONTRADICCION_LLM")}
