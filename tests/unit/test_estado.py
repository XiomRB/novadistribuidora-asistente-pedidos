from datetime import date
from decimal import Decimal
from itertools import product

import pytest

from app.dominio.errores import InvarianteViolada
from app.dominio.estado import determinar_estado, motivos_revision, verificar_invariantes
from app.dominio.resultado import Estado, Linea, Motivo, Pendiente, ResultadoCierre

AMBIGUO = Pendiente(Motivo.PRODUCTO_AMBIGUO, "aceite", ("A", "B"))
NO_EXISTE = Pendiente(Motivo.PRODUCTO_NO_EXISTE, "cerveza")
AGOTADO = Pendiente(Motivo.AGOTADO_SIN_SUSTITUTO, "Producto X", ("X",))


class TestPrioridadDeEstados:
    @pytest.mark.parametrize(
        ("eventos", "lineas", "pendientes", "credito", "esperado"),
        [
            # 1. Sin eventos de pedido: siempre fuera de alcance.
            (False, False, False, False, Estado.FUERA_DE_ALCANCE),
            (False, False, False, True, Estado.FUERA_DE_ALCANCE),
            # 2. Pendientes: requiere revisión aunque no haya líneas.
            (True, False, True, False, Estado.REQUIERE_REVISION),
            (True, False, True, True, Estado.REQUIERE_REVISION),
            (True, True, True, False, Estado.REQUIERE_REVISION),
            (True, True, True, True, Estado.REQUIERE_REVISION),
            # 3. Pedido vaciado (sin líneas ni pendientes): fuera de alcance.
            (True, False, False, False, Estado.FUERA_DE_ALCANCE),
            (True, False, False, True, Estado.FUERA_DE_ALCANCE),
            # 4. Líneas con crédito excedido.
            (True, True, False, True, Estado.REQUIERE_REVISION),
            # 5. Confirmado.
            (True, True, False, False, Estado.CONFIRMADO),
        ],
    )
    def test_tabla(self, eventos, lineas, pendientes, credito, esperado):
        assert (
            determinar_estado(hay_eventos_pedido=eventos, hay_lineas=lineas, hay_pendientes=pendientes, credito=credito)
            is esperado
        )

    def test_ninguna_combinacion_confirma_con_pendientes_o_credito(self):
        for eventos, lineas, pendientes, credito in product([False, True], repeat=4):
            estado = determinar_estado(hay_eventos_pedido=eventos, hay_lineas=lineas, hay_pendientes=pendientes, credito=credito)
            if estado is Estado.CONFIRMADO:
                assert eventos and lineas and not pendientes and not credito

    def test_sin_eventos_nunca_requiere_revision(self):
        for lineas, pendientes, credito in product([False, True], repeat=3):
            estado = determinar_estado(hay_eventos_pedido=False, hay_lineas=lineas, hay_pendientes=pendientes, credito=credito)
            assert estado is Estado.FUERA_DE_ALCANCE


class TestMotivos:
    def test_orden_de_aparicion_sin_duplicados(self):
        assert motivos_revision([NO_EXISTE, AMBIGUO, NO_EXISTE, AGOTADO], credito=False) == (
            Motivo.PRODUCTO_NO_EXISTE,
            Motivo.PRODUCTO_AMBIGUO,
            Motivo.AGOTADO_SIN_SUSTITUTO,
        )

    def test_credito_al_final(self):
        assert motivos_revision([AMBIGUO], credito=True) == (Motivo.PRODUCTO_AMBIGUO, Motivo.CREDITO_EXCEDIDO)
        assert motivos_revision([], credito=True) == (Motivo.CREDITO_EXCEDIDO,)

    def test_sin_motivos(self):
        assert motivos_revision([], credito=False) == ()

    def test_credito_no_puede_ser_pendiente(self):
        with pytest.raises(ValueError):
            Pendiente(Motivo.CREDITO_EXCEDIDO, "x")


def _linea(subtotal="100.00"):
    return Linea("G01", Decimal(1), Decimal(subtotal), Decimal(0), Decimal(subtotal))


def _resultado(**cambios):
    base = dict(
        cliente_id="K01",
        estado=Estado.CONFIRMADO,
        lineas=(_linea(),),
        total=Decimal("100.00"),
        fecha_entrega=date(2026, 12, 3),
        sustituciones=(),
        pendientes=(),
        motivos_revision=(),
    )
    base.update(cambios)
    return ResultadoCierre(**base)


class TestInvariantes:
    def test_resultado_valido(self):
        verificar_invariantes(_resultado())

    @pytest.mark.parametrize(
        "cambios",
        [
            {"total": Decimal("99.99")},
            {"fecha_entrega": None},
            {"pendientes": (AMBIGUO,), "motivos_revision": (Motivo.PRODUCTO_AMBIGUO,)},  # confirmado con pendiente
            {"motivos_revision": (Motivo.CREDITO_EXCEDIDO,)},  # confirmado con motivo
            {"estado": Estado.REQUIERE_REVISION},  # revisión sin motivos
            {"estado": Estado.REQUIERE_REVISION, "pendientes": (AMBIGUO,), "motivos_revision": ()},
            {
                "estado": Estado.REQUIERE_REVISION,
                "pendientes": (AMBIGUO,),
                "motivos_revision": (Motivo.CREDITO_EXCEDIDO, Motivo.PRODUCTO_AMBIGUO),
            },  # crédito no va al final
            {"estado": Estado.FUERA_DE_ALCANCE},  # fuera con líneas
            {"lineas": (), "total": Decimal("0.00")},  # sin líneas pero con fecha
        ],
    )
    def test_violaciones_detectadas(self, cambios):
        with pytest.raises(InvarianteViolada):
            verificar_invariantes(_resultado(**cambios))

    def test_fuera_de_alcance_valido(self):
        verificar_invariantes(
            _resultado(estado=Estado.FUERA_DE_ALCANCE, lineas=(), total=Decimal("0.00"), fecha_entrega=None)
        )
