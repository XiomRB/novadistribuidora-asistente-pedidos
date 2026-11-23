"""Prueba A: pedido cancelado en el cierre de E1a (sin modificar su código).

hay_eventos_pedido=True con líneas, pendientes y sustituciones vacías debe producir
fuera_de_alcance, sin evaluar el crédito y sin violar invariantes.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.dominio import cierre
from app.dominio.estado import verificar_invariantes
from app.dominio.resultado import Estado, Motivo, Pendiente

MARTES = datetime(2026, 12, 1, 10, 0)


class CreditoNoDebeEvaluarse(AssertionError):
    pass


@pytest.fixture
def espia_credito(monkeypatch):
    llamadas = []
    original = cierre.credito_excedido

    def espia(*args, **kwargs):
        llamadas.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(cierre, "credito_excedido", espia)
    return llamadas


def test_pedido_cancelado_es_fuera_de_alcance_sin_credito(datos, monkeypatch):
    def prohibido(*args, **kwargs):
        raise CreditoNoDebeEvaluarse("el crédito no debe evaluarse en un pedido cancelado")

    monkeypatch.setattr(cierre, "credito_excedido", prohibido)
    # K03 tiene saldo (1200) mayor que su límite (1000): si se evaluara, habría crédito excedido.
    resultado = cierre.cerrar_pedido(
        cliente_id="K03",
        fecha_hora=MARTES,
        lineas_solicitadas=[],
        pendientes=[],
        sustituciones=[],
        hay_eventos_pedido=True,
        datos=datos,
    )
    assert resultado.estado is Estado.FUERA_DE_ALCANCE
    assert resultado.lineas == () and resultado.pendientes == () and resultado.sustituciones == ()
    assert resultado.motivos_revision == ()
    assert resultado.total == Decimal("0.00") and resultado.fecha_entrega is None
    verificar_invariantes(resultado)


def test_control_el_espia_detecta_la_evaluacion_de_credito(datos, espia_credito):
    resultado = cierre.cerrar_pedido(
        cliente_id="K03",
        fecha_hora=MARTES,
        lineas_solicitadas=[],
        pendientes=[Pendiente(Motivo.PRODUCTO_NO_EXISTE, "cerveza")],
        hay_eventos_pedido=True,
        datos=datos,
    )
    assert len(espia_credito) == 1
    assert resultado.motivos_revision == (Motivo.PRODUCTO_NO_EXISTE, Motivo.CREDITO_EXCEDIDO)


def test_consulta_pura_tampoco_evalua_credito(datos, espia_credito):
    resultado = cierre.cerrar_pedido(
        cliente_id="K03", fecha_hora=MARTES, lineas_solicitadas=[], pendientes=[], hay_eventos_pedido=False, datos=datos
    )
    assert resultado.estado is Estado.FUERA_DE_ALCANCE and espia_credito == []
