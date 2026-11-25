"""Escenarios de principio a fin (tabla 3.9 del plan corregido de E1b) y prueba A en el orquestador."""

from decimal import Decimal

import pytest

from app.dominio import cierre
from app.dominio.clasificacion import Clasificacion
from app.dominio.estado import verificar_invariantes
from app.dominio.resultado import Estado
from app.mensajes import confirmacion
from tests.fixtures.historial_e1b2 import ev
from tests.fixtures.pedido_e1b2b import cargar_recursos, frag, lineas, pendientes, procesar


@pytest.fixture(scope="module")
def rec(tmp_path_factory):
    return cargar_recursos(tmp_path_factory.mktemp("escenarios"))[1]


@pytest.fixture
def credito_prohibido(monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("el crédito no debe evaluarse")

    monkeypatch.setattr(cierre, "credito_excedido", prohibido)


def comprobar(r, clasificacion, estado):
    verificar_invariantes(r.cierre)
    assert r.clasificacion is clasificacion and r.cierre.estado is estado


class TestTabla39:
    def test_consulta_pura_sin_evaluar_credito(self, rec, credito_prohibido):
        mensaje = "¿Tienen gaseosa sol de 600?"
        r = procesar(rec, [mensaje], consultas=[frag(0, mensaje)], cliente="K03")  # K03: saldo > límite
        comprobar(r, Clasificacion.CONSULTA, Estado.FUERA_DE_ALCANCE)
        assert r.mensaje_cliente == f"¡Buenos días! {confirmacion.CONSULTA}"

    def test_consulta_con_cantidad_sin_compra(self, rec):
        r = procesar(rec, ["¿tienen 3 fardos de gaseosa sol 600?"])
        comprobar(r, Clasificacion.CONSULTA, Estado.FUERA_DE_ALCANCE)

    def test_consulta_con_evento_erroneo_del_interprete(self, rec):
        r = procesar(rec, ["¿Cuánto cuesta el aceite girasol?"], [ev(1, 0, "agregar", "aceite girasol", producto="aceite girasol")])
        comprobar(r, Clasificacion.CONSULTA, Estado.FUERA_DE_ALCANCE)
        assert [d.codigo for d in r.diagnostico.eventos_descartados] == ["DESCARTADO_CONSULTA"]

    def test_consulta_seguida_de_pedido(self, rec):
        mensaje = "¿Tienen gaseosa sol de 600? Si hay, mándeme 2"
        r = procesar(rec, [mensaje], [ev(1, 0, "agregar", "mándeme 2", producto="gaseosa sol de 600", cantidad="2")],
                     consultas=[frag(0, "¿Tienen gaseosa sol de 600?")])
        comprobar(r, Clasificacion.PEDIDO, Estado.CONFIRMADO)
        assert lineas(r) == [("GS6", "2")] and r.cierre.pendientes == ()

    def test_consulta_en_un_mensaje_y_pedido_en_otro(self, rec):
        r = procesar(rec, ["¿La próxima semana tendrán cloro claro?", "mándeme 3 de frijol negro"],
                     [ev(1, 1, "agregar", "3 de frijol negro", producto="frijol negro", cantidad="3")])
        comprobar(r, Clasificacion.PEDIDO, Estado.CONFIRMADO)
        assert lineas(r) == [("FN1", "3")] and r.cierre.pendientes == ()

    def test_pedido_en_forma_de_pregunta(self, rec):
        r = procesar(rec, ["¿me manda 2 fardos de gaseosa sol 600?"],
                     [ev(1, 0, "agregar", "2 fardos de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2", unidad="venta", unidad_texto="fardos")])
        comprobar(r, Clasificacion.PEDIDO, Estado.CONFIRMADO)
        assert lineas(r) == [("GS6", "2")]

    def test_pedido_cancelado(self, rec):
        r = procesar(rec, ["2 de gaseosa sol 600", "no, mejor no me mande nada"], [
            ev(1, 0, "agregar", "2 de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2"),
            ev(2, 1, "quitar", "no me mande nada", ref="e1"),
        ])
        comprobar(r, Clasificacion.PEDIDO_CANCELADO, Estado.FUERA_DE_ALCANCE)
        assert r.mensaje_cliente == f"¡Buenos días! {confirmacion.CANCELADO}"

    def test_habitual_excluido_por_completo(self, rec):
        # K04: el habitual (P-20, entregado el mismo día de la recepción) solo tiene leche.
        r = procesar(rec, ["lo de siempre pero sin la leche"], [
            ev(1, 0, "habitual", "lo de siempre"),
            ev(2, 0, "quitar", "sin la leche", producto="leche"),
        ])
        comprobar(r, Clasificacion.PEDIDO_CANCELADO, Estado.FUERA_DE_ALCANCE)
        assert r.diagnostico.habitual_usado is True

    def test_vaciado_por_correccion(self, rec):
        r = procesar(rec, ["3 de frijol negro", "no, que sean 0"], [
            ev(1, 0, "agregar", "3 de frijol negro", producto="frijol negro", cantidad="3"),
            ev(2, 1, "corregir", "que sean 0", cantidad="0", ref="e1"),
        ])
        comprobar(r, Clasificacion.PEDIDO_CANCELADO, Estado.FUERA_DE_ALCANCE)

    def test_quitar_sin_destino(self, rec):
        r = procesar(rec, ["quíteme la gaseosa del pedido de ayer"], [ev(1, 0, "quitar", "quíteme la gaseosa", producto="gaseosa")])
        comprobar(r, Clasificacion.SIN_EFECTO, Estado.FUERA_DE_ALCANCE)
        assert r.mensaje_cliente == f"¡Buenos días! {confirmacion.SIN_EFECTO}"


class TestPruebaA:
    """Pedido cancelado por el orquestador: fuera_de_alcance sin evaluar el crédito."""

    def test_cancelado_no_evalua_credito(self, rec, credito_prohibido):
        r = procesar(rec, ["2 de gaseosa sol 600", "mejor no"], [
            ev(1, 0, "agregar", "2 de gaseosa sol 600", producto="gaseosa sol 600", cantidad="2"),
            ev(2, 1, "quitar", "mejor no", ref="e1"),
        ], cliente="K03")
        comprobar(r, Clasificacion.PEDIDO_CANCELADO, Estado.FUERA_DE_ALCANCE)
        assert r.cierre.total == Decimal("0.00") and r.cierre.fecha_entrega is None and r.cierre.motivos_revision == ()

    def test_control_con_pendiente_si_evalua_credito(self, rec):
        r = procesar(rec, ["2 de cerveza"], [ev(1, 0, "agregar", "2 de cerveza", producto="cerveza", cantidad="2")], cliente="K03")
        assert [m.value for m in r.cierre.motivos_revision] == ["producto_no_existe", "credito_excedido"]


def test_pedido_con_habitual_sustituciones_y_pendientes_por_el_orquestador(rec):
    r = procesar(rec, ["lo de siempre"], [ev(1, 0, "habitual", "lo de siempre")], cliente="K01")
    comprobar(r, Clasificacion.PEDIDO, Estado.REQUIERE_REVISION)
    assert lineas(r) == [("GS2", "3"), ("AC1", "1"), ("PC2", "2")]
    assert [m for m, _, _ in pendientes(r)] == ["agotado_sin_sustituto", "producto_no_existe"]
    assert "En lugar de Gaseosa Sol 3 L le enviaremos Gaseosa Sol 2 L." in r.mensaje_cliente
